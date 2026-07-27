from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from models import FeedItem
from recollection import (
    backend_recollection_key,
    backend_reference_key,
    legacy_semantic_key,
    metadata_is_complete,
    reduced_reference_compatible,
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


def _compatible_candidate(item: FeedItem, candidates: list[FeedItem]) -> bool:
    return any(
        reduced_reference_compatible(
            left_title=item.title,
            left_evidence=item.evidence,
            right_title=candidate.title,
            right_evidence=candidate.evidence,
        )
        for candidate in candidates
    )


def merge_items(
    old: list[FeedItem],
    new: list[FeedItem],
    *,
    now: datetime,
    retention_days: int,
) -> list[FeedItem]:
    cutoff = now - timedelta(days=retention_days)

    new_url_keys = {_url_key(item) for item in new}
    new_legacy_keys = {_legacy_key(item) for item in new}

    new_by_full: dict[str, list[FeedItem]] = defaultdict(list)
    new_by_reference: dict[str, list[FeedItem]] = defaultdict(list)
    new_incomplete_by_reference: dict[str, list[FeedItem]] = defaultdict(list)
    for item in new:
        full_key = _refresh_recollection_key(item)
        reference_key = _reference_key(item)
        new_by_full[full_key].append(item)
        new_by_reference[reference_key].append(item)
        if not _metadata_complete(item):
            new_incomplete_by_reference[reference_key].append(item)

    # Ordem de decisão:
    # 1. Mesmo URL oficial: substitui, inclusive após correção de extração.
    # 2. Mesma chave editorial completa: ainda exige conteúdo discriminante
    #    compatível, pois tipo/número/página não identificam globalmente o órgão.
    # 3. Metadados incompletos: exige a mesma referência normativa e a mesma
    #    compatibilidade de conteúdo.
    old_kept: list[FeedItem] = []
    for item in old:
        current_key = _refresh_recollection_key(item)
        reference_key = _reference_key(item)
        complete = _metadata_complete(item)

        replaced = _url_key(item) in new_url_keys
        if not replaced:
            replaced = _compatible_candidate(item, new_by_full.get(current_key, []))
        if not replaced:
            candidates = (
                new_by_reference.get(reference_key, [])
                if not complete
                else new_incomplete_by_reference.get(reference_key, [])
            )
            replaced = _compatible_candidate(item, candidates)
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
