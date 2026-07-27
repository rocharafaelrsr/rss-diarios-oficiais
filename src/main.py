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

import yaml

from diarios.dodf import DodfCollector
from diarios.dou import DouCollector, InlabsAuthenticationError
from http_client import HttpClient
from models import Document, FeedItem
from rss_writer import write_rss
from rules import Rule
from state import load_items, merge_items, save_items
from text_utils import excerpt_around, sha256_text

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


def compact_title(text: str, limit: int = 205) -> str:
    value = " ".join(text.replace("…", " ").split()).strip(" .;:-")
    if len(value) <= limit:
        return value
    return value[: limit - 1].rsplit(" ", 1)[0] + "…"


def days_to_collect(today: date, lookback: int) -> list[date]:
    return [today - timedelta(days=offset) for offset in range(max(1, lookback))]


def classify(documents: list[Document], rules: list[Rule], collected_at: datetime) -> list[FeedItem]:
    output: list[FeedItem] = []
    for document in documents:
        combined = f"{document.title}\n{document.text}"
        for rule in rules:
            matched = rule.match(document.source, combined)
            if not matched:
                continue
            excerpt = excerpt_around(combined, matched)
            guid = sha256_text(
                document.source,
                document.url,
                document.page or "",
                rule.id,
                excerpt[:240],
            )
            prefix = "DODF" if document.source == "dodf" else "DOU"
            location_parts = [part for part in [document.edition, document.section] if part]
            if document.page:
                location_parts.append(f"p. {document.page}")
            location = " · ".join(location_parts)
            if document.source == "dodf":
                raw_title = f"[{prefix}] {rule.label} | {location} | {excerpt}"
            else:
                raw_title = f"[{prefix}] {rule.label} | {document.title} | {excerpt}"
            output.append(
                FeedItem(
                    guid=guid,
                    category=rule.id,
                    category_label=rule.label,
                    priority=rule.priority,
                    source=document.source,
                    source_label=document.source_label,
                    title=compact_title(raw_title),
                    link=document.url,
                    published_at=document.published_at.isoformat(),
                    collected_at=collected_at.isoformat(),
                    edition=document.edition,
                    section=document.section,
                    page=document.page,
                    excerpt=excerpt,
                    matched_terms=matched,
                )
            )
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta DODF/DOU e gera feeds RSS 2.0")
    parser.add_argument("--config", default="config/monitors.yml")
    parser.add_argument("--date", help="Data de referência no formato AAAA-MM-DD")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    project = config["project"]
    today = date.fromisoformat(args.date) if args.date else datetime.now(BRT).date()
    now = datetime.now(BRT)
    expanded_rules = expand_rule_tokens(config["rules"], next_year=today.year + 1)
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
    days = days_to_collect(today, int(project.get("lookback_days", 3)))

    if config["sources"]["dodf"].get("enabled", True):
        collector = DodfCollector(client, config["sources"]["dodf"]["daily_url"])
        count_before = len(documents)
        for day in days:
            try:
                documents.extend(collector.collect(day))
            except Exception as exc:  # preserva a outra fonte
                LOG.exception("Falha geral no DODF em %s", day)
                status["errors"].append({"source": "dodf", "date": day.isoformat(), "error": str(exc)[:300]})
        status["sources"]["dodf"] = {"documents": len(documents) - count_before}

    dou_required_failure = False
    if config["sources"]["dou"].get("enabled", True):
        dou_cfg = config["sources"]["dou"]
        collector = DouCollector(
            client,
            dou_cfg["inlabs_base_url"],
            os.getenv("INLABS_EMAIL", ""),
            os.getenv("INLABS_PASSWORD", ""),
        )
        count_before = len(documents)
        for day in days:
            try:
                documents.extend(collector.collect(day))
            except InlabsAuthenticationError as exc:
                LOG.error("DOU/INLABS: %s", exc)
                status["errors"].append({"source": "dou", "date": day.isoformat(), "error": str(exc)[:300]})
                dou_required_failure = bool(dou_cfg.get("required", True))
                break
            except Exception as exc:
                LOG.exception("Falha geral no DOU em %s", day)
                status["errors"].append({"source": "dou", "date": day.isoformat(), "error": str(exc)[:300]})
        status["sources"]["dou"] = {"documents": len(documents) - count_before}

    new_items = classify(documents, rules, now)
    items_path = root / "data/items.json"
    all_items = merge_items(
        load_items(items_path),
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
        }
    )
    status_path = root / "docs/status.json"
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    LOG.info("Concluído: %d documentos, %d correspondências novas, %d itens armazenados", len(documents), len(new_items), len(all_items))

    # Falha total de ambas as fontes deve aparecer no Actions; falha parcial é
    # registrada no status e não impede a publicação do que foi obtido.
    if dou_required_failure:
        return 3
    if status["errors"] and not documents:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
