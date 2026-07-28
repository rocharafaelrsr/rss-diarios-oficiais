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
    # Uniformiza as grafias editoriais de número antes de aplicar regras. Em
    # NFKD, "º" vira "o", enquanto "n.º" vira "n.o" e "n°" preserva o grau.
    value = re.sub(r"\bn\s*(?:\.\s*)?(?:o|°)\s*(?=\d)", "no ", value)
    # O Edital 01/2022 é uma identidade documental: zero à esquerda e prefixo
    # "nº" não devem alterar a correspondência estrita.
    value = re.sub(r"\bedital\s+(?:no\s+)?0?1/2022\b", "edital no 01/2022", value)
    # Os títulos da carreira variam em gênero e número, mas representam a mesma
    # âncora semântica. A canonicalização é restrita às denominações ATUB para
    # que regras e validação estrita usem a mesma identidade textual.
    value = re.sub(
        r"\bauditor(?:a|es|as)?\s+fisc(?:al|ais)\s+de\s+atividades\s+urbanas\b",
        "auditor fiscal de atividades urbanas",
        value,
    )
    value = re.sub(
        r"\bauditor(?:a|es|as)?\s+de\s+atividades\s+urbanas\b",
        "auditor de atividades urbanas",
        value,
    )
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
