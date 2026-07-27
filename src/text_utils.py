from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from collections.abc import Iterable

SPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKD", text or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.casefold()
    return " " + SPACE_RE.sub(" ", value).strip() + " "


def clean_text(text: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(text or "")).strip()


def sha256_text(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()


def excerpt_around(text: str, needles: Iterable[str], radius: int = 520) -> str:
    clean = clean_text(text)
    folded = normalize(clean)
    positions: list[int] = []
    for needle in needles:
        n = normalize(needle).strip()
        if not n:
            continue
        pos = folded.find(n)
        if pos >= 0:
            positions.append(pos)
    center = min(positions) if positions else 0
    start = max(0, center - radius)
    end = min(len(clean), center + radius)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "… " + snippet
    if end < len(clean):
        snippet += " …"
    return snippet
