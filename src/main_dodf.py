from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests

from diarios.dodf_resilient import ResilientDodfCollector
from http_client import HttpClient
from main import BRT, classify, days_to_collect, expand_rule_tokens, load_config
from models import FeedItem
from presentation import sanitize_stored_items
from rss_writer import write_rss
from rules import Rule
from state import load_items, merge_items, save_items

LOG = logging.getLogger("rss_diarios.dodf")


def dodf_business_day_health(
    days: list[date],
    day_counts: dict[str, int | None],
) -> dict[str, Any]:
    business_days = [day for day in days if day.weekday() < 5]
    with_documents = [
        day
        for day in business_days
        if (day_counts.get(day.isoformat()) or 0) > 0
    ]
    return {
        "business_days_checked": [day.isoformat() for day in business_days],
        "business_days_with_documents": [day.isoformat() for day in with_documents],
        "healthy": not business_days or bool(with_documents),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Coleta DODF e gera feeds RSS 2.0")
    parser.add_argument("--config", default="config/monitors.yml")
    parser.add_argument("--date", help="Data de referência no formato AAAA-MM-DD")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--lookback", type=int, help="Sobrescreve a quantidade de dias consultados")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    root = Path(__file__).resolve().parents[1]
    config = load_config(root / args.config)
    project = config["project"]
    dodf_cfg = config["sources"]["dodf"]
    today = date.fromisoformat(args.date) if args.date else datetime.now(BRT).date()
    next_year = today.year + 1
    now = datetime.now(BRT)
    lookback = args.lookback if args.lookback is not None else int(project.get("lookback_days", 3))
    days = days_to_collect(today, lookback)

    status: dict[str, Any] = {
        "started_at": now.isoformat(),
        "reference_date": today.isoformat(),
        "sources": {},
        "errors": [],
    }
    documents = []

    client = HttpClient(
        timeout=int(project.get("request_timeout_seconds", 35)),
        user_agent=str(project["user_agent"]),
    )
    collector = ResilientDodfCollector(
        client,
        dodf_cfg["daily_url"],
        dodf_cfg.get("sinj_search_url", "https://www.sinj.df.gov.br/sinj/Pesquisas.aspx"),
    )

    day_counts: dict[str, int | None] = {}
    for day in days:
        try:
            day_documents = collector.collect(day)
            day_counts[day.isoformat()] = len(day_documents)
            documents.extend(day_documents)
        except Exception as exc:
            day_counts[day.isoformat()] = None
            LOG.exception("Falha geral no DODF em %s", day)
            status["errors"].append(
                {"source": "dodf", "date": day.isoformat(), "error": str(exc)[:500]}
            )
            if isinstance(exc, (requests.RequestException, ConnectionError, RuntimeError)):
                LOG.warning("DODF: fallback indisponível; datas restantes ficam para a próxima execução")
                break

    health = dodf_business_day_health(days, day_counts)
    required_failure = False
    if not health["healthy"]:
        message = (
            "Nenhum documento do DODF foi obtido nos dias úteis da janela; "
            "o resultado vazio não será publicado como coleta válida."
        )
        status["errors"].append(
            {"source": "dodf", "date": today.isoformat(), "error": message}
        )
        required_failure = bool(dodf_cfg.get("required", True))
        LOG.error("DODF: %s", message)

    status["sources"]["dodf"] = {
        "documents": len(documents),
        "backend": collector.backend,
        "fallback_reason": collector.fallback_reason or None,
        "documents_by_date": day_counts,
        "primary_attempts": collector.primary_attempts,
        "primary_circuit_open": collector.primary_circuit_open,
        "primary_circuit_reason": collector.primary_circuit_reason or None,
        "primary_skipped_dates": collector.primary_skipped_dates,
        **health,
    }

    items_path = root / "data/items.json"
    stored_raw = load_items(items_path)
    hard_failure_without_documents = bool(
        not documents and (required_failure or status["errors"])
    )

    if hard_failure_without_documents:
        new_items: list[FeedItem] = []
        all_items = stored_raw
        pruned_items = 0
        state_updated = False
        LOG.warning("Estado e feeds preservados devido à falha integral da coleta")
    else:
        expanded_rules = expand_rule_tokens(config["rules"], next_year=next_year)
        rules = [Rule.from_dict(value) for value in expanded_rules]
        new_items = classify(documents, rules, now, next_year=next_year)
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
        state_updated = True

    status.update(
        {
            "finished_at": datetime.now(BRT).isoformat(),
            "documents_examined": len(documents),
            "new_matches": len(new_items),
            "stored_items": len(all_items),
            "items_removed_out_of_scope": pruned_items,
            "state_updated": state_updated,
        }
    )
    (root / "docs/status-dodf.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    LOG.info(
        "Concluído: %d documentos, %d correspondências novas, %d itens armazenados, %d removidos do escopo",
        len(documents),
        len(new_items),
        len(all_items),
        pruned_items,
    )

    if required_failure:
        return 4
    if status["errors"] and not documents:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
