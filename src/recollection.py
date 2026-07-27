from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from text_utils import clean_text, normalize, sha256_text

ACT_TYPE_PATTERN = (
    r"instrucao\s+normativa|ordem\s+de\s+servico|"
    r"lei|portaria|edital|decreto|resolucao|ato|despacho|aviso"
)
# A expressão roda sobre texto normalizado, portanto qualificadores acentuados,
# como CONVOCAÇÃO, já chegam como "convocacao".
ACT_REFERENCE_RE = re.compile(
    rf"\b(?P<kind>{ACT_TYPE_PATTERN})\b"
    r"(?P<qualifier>(?:\s+(?!n\s*[º°o]?\s*\d)[a-z0-9./-]+){0,8})"
    r"\s+n\s*[º°o]?\s*(?P<number>\d[\d\s./-]*)",
    flags=re.I,
)
SEMANTIC_PREFIX_RE = re.compile(r"^\[(?:DOU|DODF)\]\s*", flags=re.I)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalize(value).strip()).strip("-")


def _canonical_edition(value: str) -> str:
    normalized = normalize(value).strip()
    normalized = re.sub(r"^(?:(?:dodf|dou)\s+)?(?:edicao\s+)?", "", normalized)
    normalized = re.sub(r"\bedicao\b", " ", normalized)
    return _slug(normalized)


def _canonical_section(value: str) -> str:
    normalized = normalize(value).strip()
    normalized = re.sub(r"^secao\s*", "", normalized)
    normalized = re.sub(r"^do(?=\d)", "", normalized)
    return _slug(normalized)


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


def _canonical_act_number(value: str) -> str:
    groups = re.findall(r"\d+", value)
    if not groups:
        return ""
    # 001/2026, 1-2026 e 01 / 2026 são a mesma referência. Pontos sem
    # ano final são tratados como separadores de milhar: 15.300 == 15300.
    if len(groups) >= 2 and len(groups[-1]) == 4 and 1900 <= int(groups[-1]) <= 2199:
        main = int("".join(groups[:-1]))
        return f"{main}/{int(groups[-1])}"
    return str(int("".join(groups)))


def _canonical_act_match(match: re.Match[str]) -> str:
    kind = re.sub(r"\s+", "-", match.group("kind").strip())
    qualifier = _slug(match.group("qualifier"))
    number = _canonical_act_number(match.group("number"))
    parts = [kind]
    if qualifier:
        parts.append(qualifier)
    parts.append(number)
    return ":".join(parts)


def _act_reference(title: str, evidence: str) -> str:
    """Extrai e canoniza a identificação normativa compartilhada pelos backends."""
    candidates = [clean_text(evidence), clean_text(title)]

    # Primeiro procura o cabeçalho, antes de citações legais posteriores. A faixa
    # cobre prefixos editoriais e qualificadores como EDITAL DE CONVOCAÇÃO.
    for candidate in candidates:
        normalized = normalize(candidate).strip()
        if not normalized:
            continue
        match = ACT_REFERENCE_RE.search(normalized[:420])
        if match:
            return _canonical_act_match(match)

    for candidate in candidates:
        normalized = normalize(candidate).strip()
        if not normalized:
            continue
        match = ACT_REFERENCE_RE.search(normalized)
        if match:
            return _canonical_act_match(match)
    return "semantic:" + _canonical_semantic_title(title)


def metadata_is_complete(*, source: str, edition: str, section: str, page: int | None) -> bool:
    """Indica se os metadados necessários estão presentes para comparação estrita."""
    source_norm = normalize(source).strip()
    if source_norm == "dou":
        return bool(clean_text(edition) and clean_text(section) and page is not None)
    # O DODF não usa seção de forma consistente; edição e página são suficientes.
    return bool(clean_text(edition) and page is not None)


def backend_reference_key(
    *,
    source: str,
    category: str,
    published_at: str,
    title: str,
    evidence: str,
) -> str:
    """Chave normativa usada quando um backend omite edição, seção ou página."""
    return sha256_text(
        normalize(source).strip(),
        normalize(category).strip(),
        published_at[:10],
        _act_reference(title, evidence),
    )


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
    """Chave completa do ato, independente da URL e sensível a sufixos editoriais."""
    return sha256_text(
        normalize(source).strip(),
        normalize(category).strip(),
        published_at[:10],
        _canonical_edition(edition),
        _canonical_section(section),
        page if page is not None else "",
        _act_reference(title, evidence),
    )


def url_recollection_key(
    *,
    source: str,
    category: str,
    published_at: str,
    link: str,
    page: int | None,
) -> str:
    """Alias para garantir substituição após correções de extração no mesmo link."""
    parsed = urlsplit(link)
    canonical_link = urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.query, "")
    )
    return sha256_text(source, category, published_at[:10], canonical_link, page or "")


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
        _canonical_edition(edition),
        _canonical_section(section),
        page if page is not None else "",
        _canonical_semantic_title(title),
    )
