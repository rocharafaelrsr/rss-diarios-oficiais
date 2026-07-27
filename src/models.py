from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Document:
    source: str
    source_label: str
    title: str
    url: str
    published_at: datetime
    text: str
    edition: str = ""
    section: str = ""
    page: int | None = None
    publication_type: str = ""
    organization: str = ""


@dataclass(slots=True)
class FeedItem:
    guid: str
    category: str
    category_label: str
    priority: int
    source: str
    source_label: str
    title: str
    link: str
    published_at: str
    collected_at: str
    edition: str
    section: str
    page: int | None
    excerpt: str
    matched_terms: list[str]
    evidence: str = ""
    identity: str = ""
    recollection_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "FeedItem":
        payload = dict(value)
        payload.setdefault("evidence", "")
        payload.setdefault("identity", "")
        payload.setdefault("recollection_key", "")
        # O formato antigo usava barras verticais e guardava o texto-fonte no
        # próprio excerpt. Recupera essa evidência para a migração determinística.
        if not payload["evidence"] and " | " in str(payload.get("title", "")):
            payload["evidence"] = str(payload.get("excerpt", ""))
        return cls(**payload)
