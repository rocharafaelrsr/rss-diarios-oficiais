from __future__ import annotations

import re

from text_utils import clean_text, normalize, sha256_text

ACT_REFERENCE_RE = re.compile(
    r"\b(?:LEI|PORTARIA|EDITAL|DECRETO|RESOLUÇÃO|INSTRUÇÃO\s+NORMATIVA|"
    r"ATO|DESPACHO|ORDEM\s+DE\s+SERVIÇO|AVISO)"
    r"(?:\s+[A-Z0-9./-]+){0,5}\s+N[º°O]?\s*\d[\d./-]*",
    flags=re.I | re.U,
)
SEMANTIC_PREFIX_RE = re.compile(r"^\[(?:DOU|DODF)\]\s*", flags=re.I)


def _canonical_numbered_field(value: str) -> str:
    normalized = normalize(value).strip()
    numbers = re.findall(r"\d+", normalized)
    return ".".join(numbers) if numbers else normalized


def _canonical_semantic_title(title: str) -> str:
    semantic = SEMANTIC_PREFIX_RE.sub("", clean_text(title))
    value = normalize(semantic).strip()
    # Versões antigas e novas dos cards podem alternar entre “para Analista” e
    # “para cargos de Analista”. Essa diferença não identifica outro ato.
    value = re.sub(
        r"\bpara\s+(?:o\s+)?(?:provimento\s+de\s+)?(?:os?\s+)?cargos?\s+de\b",
        "para",
        value,
    )
    return re.sub(r"\s+", " ", value).strip()


def _act_reference(title: str, evidence: str) -> str:
    """Extrai a identificação normativa compartilhada pelos backends oficiais."""
    for candidate in (clean_text(evidence), clean_text(title)):
        if not candidate:
            continue
        match = ACT_REFERENCE_RE.search(candidate)
        if match:
            return normalize(match.group(0)).strip()
    return _canonical_semantic_title(title)


def backend_recollection_key(
    *,
    source: str,
    category: str,
    published_at: str,
    edition: str,
    section: str,
    page: int | None,
    title: str,
    evidence: str,
) -> str:
    """Identifica o mesmo ato sem depender da URL usada para encontrá-lo.

    INLABS e busca pública podem fornecer links diferentes para a mesma matéria.
    Data, edição, seção, página e referência normativa são metadados editoriais
    comuns aos dois caminhos de coleta.
    """
    return sha256_text(
        normalize(source).strip(),
        normalize(category).strip(),
        published_at[:10],
        _canonical_numbered_field(edition),
        _canonical_numbered_field(section),
        page or "",
        _act_reference(title, evidence),
    )


def legacy_semantic_key(
    *,
    source: str,
    category: str,
    published_at: str,
    edition: str,
    section: str,
    page: int | None,
    title: str,
) -> str:
    """Alias limitado à migração de cards antigos que não guardavam evidência."""
    return sha256_text(
        normalize(source).strip(),
        normalize(category).strip(),
        published_at[:10],
        _canonical_numbered_field(edition),
        _canonical_numbered_field(section),
        page or "",
        _canonical_semantic_title(title),
    )
