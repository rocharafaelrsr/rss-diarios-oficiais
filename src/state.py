from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from models import FeedItem
from recollection import (
    backend_recollection_key,
    backend_reference_key,
    legacy_semantic_key,
    metadata_is_complete,
    url_recollection_key,
)


def load_items(path: Path) -> list[FeedItem]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [FeedItem.from_dict(item) for item in data if isinstance(item, dict)]


def _key(item: FeedItem) -> str:
    return item.identity or item.guid


def _full_key(item: FeedItem) -> str:
    return backend_recollection_key(
        source=item.source,
        category=item.category,
        published_at=item.published_at,
        edition=item.edition,
        section=item.section,
        page=item.page,
        title=item.title,
        evidence=item.evidence,
    )


def _reference_key(item: FeedItem) -> str:
    return backend_reference_key(
        source=item.source,
        category=item.category,
        published_at=item.published_at,
        title=item.title,
        evidence=item.evidence,
    )


def _metadata_complete(item: FeedItem) -> bool:
    return metadata_is_complete(
        source=item.source,
        edition=item.edition,
        section=item.section,
        page=item.page,
    )


def _url_key(item: FeedItem) -> str:
    return url_recollection_key(
        source=item.source,
        category=item.category,
        published_at=item.published_at,
        link=item.link,
        page=item.page,
    )


def _refresh_recollection_key(item: FeedItem) -> str:
    key = _full_key(item)
    # Persiste a chave completa nova, mas o merge também recalcula o alias da URL
    # para manter a garantia de substituição de versões antigas do mesmo link.
    item.recollection_key = key
    return key


def _legacy_key(item: FeedItem) -> str:
    return legacy_semantic_key(
        source=item.source,
        category=item.category,
        published_at=item.published_at,
        edition=item.edition,
        section=item.section,
        page=item.page,
        title=item.title,
    )


def merge_items(
    old: list[FeedItem],
    new: list[FeedItem],
    *,
    now: datetime,
    retention_days: int,
) -> list[FeedItem]:
    cutoff = now - timedelta(days=retention_days)

    new_full_keys = {_refresh_recollection_key(item) for item in new}
    new_reference_keys = {_reference_key(item) for item in new}
    new_incomplete_reference_keys = {
        _reference_key(item) for item in new if not _metadata_complete(item)
    }
    new_url_keys = {_url_key(item) for item in new}
    new_legacy_keys = {_legacy_key(item) for item in new}

    # 1. Metadados completos e iguais: usa a chave editorial estrita.
    # 2. Se um backend omitiu edição/seção/página: usa a referência normativa.
    # 3. Mesmo link: substitui ainda que uma correção tenha mudado o ato extraído.
    old_kept: list[FeedItem] = []
    for item in old:
        current_key = _refresh_recollection_key(item)
        reference_key = _reference_key(item)
        complete = _metadata_complete(item)

        replaced = current_key in new_full_keys or _url_key(item) in new_url_keys
        if not replaced:
            if not complete:
                replaced = reference_key in new_reference_keys
            else:
                replaced = reference_key in new_incomplete_reference_keys
        if not replaced and not item.evidence:
            replaced = _legacy_key(item) in new_legacy_keys
        if not replaced:
            old_kept.append(item)

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
