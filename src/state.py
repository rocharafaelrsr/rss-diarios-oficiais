from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from models import FeedItem


def load_items(path: Path) -> list[FeedItem]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [FeedItem.from_dict(item) for item in data if isinstance(item, dict)]


def _key(item: FeedItem) -> str:
    return item.identity or item.guid


def merge_items(
    old: list[FeedItem],
    new: list[FeedItem],
    *,
    now: datetime,
    retention_days: int,
) -> list[FeedItem]:
    cutoff = now - timedelta(days=retention_days)
    new_recollection_keys = {item.recollection_key for item in new if item.recollection_key}

    # Itens sem evidência vieram da versão semântica 1.1 e não conseguem gerar a
    # identidade específica do ato. Quando o mesmo link/página é recolhido, a
    # versão completa substitui o legado por meio da chave de recolhimento.
    old_kept = [
        item
        for item in old
        if not (
            not item.evidence
            and item.recollection_key
            and item.recollection_key in new_recollection_keys
        )
    ]

    merged = {_key(item): item for item in old_kept}
    for item in new:
        merged[_key(item)] = item
    kept = [item for item in merged.values() if datetime.fromisoformat(item.published_at) >= cutoff]
    kept.sort(key=lambda item: (item.published_at, item.priority), reverse=True)
    return kept


def save_items(path: Path, items: list[FeedItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([item.to_dict() for item in items], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
