from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
import yaml

from diarios.dodf import DodfCollector
from diarios.dou import InlabsAuthenticationError
from diarios.dou_structured import StructuredDouCollector
from http_client import HttpClient
from models import Document, FeedItem
from presentation import build_presentation, sanitize_stored_items, strictly_relevant
from rss_writer import write_rss
from rules import Rule
from state import load_items, merge_items, save_items
from text_utils import sha256_text

BRT = ZoneInfo("America/Sao_Paulo")
LOG = logging.getLogger("rss_diarios")


def load_config(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def expand_rule_tokens(value: Any, *, next_year: int) -> Any:
    if isinstance(value, str):
        return value.replace("${NEXT_YEAR}", str(next_year))
    if isinstance(value, list):
        return [expand_rule_tokens(item, next_year=next_year) for item in value]
    if isinstance(value, dict):
        return {key: expand_rule_tokens(item, next_year=next_year) for key, item in value.items()}
    return value


def days_to_collect(today: date, lookback: int) -> list[date]:
    return [today - timedelta(days=offset) for offset in range(max(1, lookback))]


def classify(
    documents: list[Document],
    rules: list[Rule],
    collected_at: datetime,
    *,
    next_year: int,
) -> list[FeedItem]:
    output: list[FeedItem] = []
    for document in documents:
        combined = f"{document.title}\n{document.text}"
        for rule in rules:
            matched = rule.match(document.source, combined)
            if not matched:
                continue
            if not strictly_relevant(rule.id, document.source, document.title, document.text, next_year):
                LOG.debug("Descartado pelo escopo estrito: %s | %s", rule.id, document.title)
                continue
            title, summary = build_presentation(document, rule.id, next_year)
            guid = sha256_text(
                document.source,
                document.url,
                document.page or "",
                rule.id,
                summary[:240],
            )
            output.append(
                FeedItem(
                    guid=guid,
                    category=rule.id,
                    category_label=rule.label,
                    priority=rule.priority,
                    source=document.source,
                    source_label=document.source_label,
                    title=title,
                    link=document.url,
                    published_at=document.published_at.isoformat(),
                    collected_at=collected_at.isoformat(),
                    edition=document.edition,
                    section=document.section,
                    page=document.page,
                    excerpt=summary,
                    matched_terms=matched,
                )
            )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta DODF/DOU e gera feeds RSS 2.0")
    parser.add_argument("--config", default="config/monitors.yml")
    parser.add_argument("--date", help="Data de referência no formato AAAA-MM-DD")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--source", choices=("all", "dodf", "dou"), default="all")
    parser.add_argument("--lookback", type=int, help="Sobrescreve a quantidade de dias consultados")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    project = config["project"]
    today = date.fromisoformat(args.date) if args.date else datetime.now(BRT).date()
    next_year = today.year + 1
    now = datetime.now(BRT)
    expanded_rules = expand_rule_tokens(config["rules"], next_year=next_year)
    rules = [Rule.from_dict(value) for value in expanded_rules]
    client = HttpClient(
        timeout=int(project.get("request_timeout_seconds", 35)),
        user_agent=str(project["user_agent"]),
    )

    status: dict[str, Any] = {
        "started_at": now.isoformat(),
        "reference_date": today.isoformat(),
        "sources": {},
        "errors": [],
    }
    documents: list[Document] = []
    lookback = args.lookback if args.lookback is not None else int(project.get("lookback_days", 3))
    days = days_to_collect(today, lookback)

    if args.source in ("all", "dodf") and config["sources"]["dodf"].get("enabled", True):
        dodf_cfg = config["sources"]["dodf"]
        collector = DodfCollector(
            client,
            dodf_cfg["daily_url"],
            dodf_cfg.get("sinj_search_url", "https://www.sinj.df.gov.br/sinj/Pesquisas.aspx"),
        )
        count_before = len(documents)
        for day in days:
            try:
                documents.extend(collector.collect(day))
            except Exception as exc:
                LOG.exception("Falha geral no DODF em %s", day)
                status["errors"].append({"source": "dodf", "date": day.isoformat(), "error": str(exc)[:500]})
                if isinstance(exc, (requests.RequestException, ConnectionError, RuntimeError)):
                    LOG.warning("DODF: circuito aberto; demais datas serão retomadas na próxima execução")
                    break
        status["sources"]["dodf"] = {
            "documents": len(documents) - count_before,
            "backend": collector.backend,
            "fallback_reason": collector.fallback_reason or None,
        }

    dou_required_failure = False
    if args.source in ("all", "dou") and config["sources"]["dou"].get("enabled", True):
        dou_cfg = config["sources"]["dou"]
        public_terms = expand_rule_tokens(dou_cfg.get("public_search_terms", []), next_year=next_year)
        collector = StructuredDouCollector(
            client,
            dou_cfg["inlabs_base_url"],
            os.getenv("INLABS_EMAIL", ""),
            os.getenv("INLABS_PASSWORD", ""),
            dou_cfg.get("public_search_url", "https://www.in.gov.br/consulta/-/buscar/dou"),
            public_terms,
        )
        count_before = len(documents)
        for day in days:
            try:
                documents.extend(collector.collect(day))
            except InlabsAuthenticationError as exc:
                LOG.error("DOU/INLABS: %s", exc)
                status["errors"].append({"source": "dou", "date": day.isoformat(), "error": str(exc)[:500]})
                dou_required_failure = bool(dou_cfg.get("required", True))
                break
            except Exception as exc:
                LOG.exception("Falha geral no DOU em %s", day)
                status["errors"].append({"source": "dou", "date": day.isoformat(), "error": str(exc)[:500]})
                dou_required_failure = bool(dou_cfg.get("required", True))
                if isinstance(exc, (requests.RequestException, ConnectionError, RuntimeError)):
                    LOG.warning("DOU: circuito aberto; demais datas serão retomadas na próxima execução")
                    break
        status["sources"]["dou"] = {
            "documents": len(documents) - count_before,
            "backend": collector.backend,
            "fallback_reason": collector.fallback_reason or None,
        }

    new_items = classify(documents, rules, now, next_year=next_year)
    items_path = root / "data/items.json"
    stored_raw = load_items(items_path)
    stored_items, pruned_items = sanitize_stored_items(stored_raw, next_year)
    all_items = merge_items(
        stored_items,
        new_items,
        now=now,
        retention_days=int(project.get("retention_days", 730)),
    )
    save_items(items_path, all_items)

    base_url = str(project["base_url"]).rstrip("/")
    max_items = int(project.get("max_items_per_feed", 300))
    for slug, feed in config["feeds"].items():
        categories = set(feed["categories"])
        selected = [item for item in all_items if item.category in categories][:max_items]
        write_rss(
            root / f"docs/feeds/{slug}.xml",
            title=feed["title"],
            description=feed["description"],
            link=f"{base_url}/feeds/{slug}.xml",
            items=selected,
            last_build=now,
        )

    status.update(
        {
            "finished_at": datetime.now(BRT).isoformat(),
            "documents_examined": len(documents),
            "new_matches": len(new_items),
            "stored_items": len(all_items),
            "items_removed_out_of_scope": pruned_items,
        }
    )
    status_name = "status.json" if args.source == "all" else f"status-{args.source}.json"
    status_path = root / "docs" / status_name
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info(
        "Concluído: %d documentos, %d correspondências novas, %d itens armazenados, %d removidos do escopo",
        len(documents),
        len(new_items),
        len(all_items),
        pruned_items,
    )

    if dou_required_failure:
        return 3
    if status["errors"] and not documents:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
