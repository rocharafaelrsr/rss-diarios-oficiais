from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from text_utils import clean_text, normalize, sha256_text

# Tipos compostos vêm primeiro para impedir que DECRETO-LEI seja lido como LEI
# e que PROJETO DE LEI seja reduzido à lei citada dentro do cabeçalho.
ACT_TYPE_PATTERN = (
    r"decreto(?:\s*[-–—]\s*|\s+)lei|"
    r"projeto\s+de\s+lei|medida\s+provisoria|"
    r"instrucao\s+normativa|ordem\s+de\s+servico|"
    r"emenda|veto|mensagem|"
    r"lei|portaria|edital|decreto|resolucao|ato|despacho|aviso"
)

ACT_REFERENCE_RE = re.compile(
    rf"\b(?P<kind>{ACT_TYPE_PATTERN})\b"
    r"(?P<qualifier>(?:\s+(?!n(?:o)?(?:\b|[º°]))[a-z][a-z0-9./-]*){0,8})"
    r"\s+(?:(?P<marker>n\s*[º°o]?)\s*)?"
    r"(?P<number>\d(?:[\d\s./\-–—]*\d)?(?:\s*[-–—]\s*[a-z]+)?)",
    flags=re.I,
)
SEMANTIC_PREFIX_RE = re.compile(r"^\[(?:DOU|DODF)\]\s*", flags=re.I)
YEAR_INTRODUCERS = {
    "de", "do", "da", "dos", "das", "para", "em", "ano", "exercicio",
    "referente", "relativo", "relativa", "relativos", "relativas",
}

REFERENCE_NOISE = {
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e", "em",
    "na", "nas", "no", "nos", "o", "os", "para", "por", "que", "se", "um", "uma",
    "ato", "aviso", "decreto", "despacho", "edital", "emenda", "instrucao", "lei",
    "medida", "mensagem", "normativa", "ordem", "portaria", "projeto", "provisoria",
    "resolucao", "servico", "veto", "autoriza", "autorizacao", "autorizada",
    "autorizado", "concurso", "publico", "realiza", "realizacao", "realizar",
    "abertura", "cargo", "cargos", "provimento", "nomeacao", "admissao", "pessoal",
    "novo", "nova", "publica", "publicacao", "instituto", "ministerio", "secretaria",
    "departamento", "agencia", "orgao", "entidade", "dou", "dodf", "diario",
    "oficial", "uniao", "distrito", "federal",
}


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
    value = re.sub(
        r"\bpara\s+(?:o\s+)?(?:provimento\s+de\s+)?(?:os?\s+)?cargos?\s+de\b",
        "para",
        value,
    )
    return re.sub(r"\s+", " ", value).strip()


def _canonical_act_number(value: str) -> str:
    normalized = normalize(value).strip()
    suffix_match = re.search(r"[-–—]\s*([a-z]+)\s*$", normalized)
    suffix = suffix_match.group(1) if suffix_match else ""
    numeric_value = normalized[: suffix_match.start()] if suffix_match else normalized
    groups = re.findall(r"\d+", numeric_value)
    if not groups:
        return ""

    if len(groups) >= 2 and len(groups[-1]) == 4 and 1900 <= int(groups[-1]) <= 2199:
        main = int("".join(groups[:-1]))
        base = f"{main}/{int(groups[-1])}"
    else:
        base = str(int("".join(groups)))
    return f"{base}-{suffix}" if suffix else base


def _canonical_act_match(match: re.Match[str]) -> str:
    kind = re.sub(r"[\s\-–—]+", "-", match.group("kind").strip())
    qualifier = _slug(match.group("qualifier"))
    number = _canonical_act_number(match.group("number"))
    parts = [kind]
    if qualifier:
        parts.append(qualifier)
    parts.append(number)
    return ":".join(parts)


def _valid_reference_match(match: re.Match[str], normalized: str) -> bool:
    """Rejeita anos redacionais quando o número do ato não tem marcador N/Nº."""
    if match.group("marker"):
        return True

    qualifier = _slug(match.group("qualifier"))
    number = _canonical_act_number(match.group("number"))
    qualifier_tokens = qualifier.split("-") if qualifier else []
    is_year = bool(re.fullmatch(r"(?:18|19|20|21)\d{2}", number))
    if is_year and qualifier_tokens and qualifier_tokens[-1] in YEAR_INTRODUCERS:
        return False
    return True


def _find_reference(candidate: str) -> str:
    normalized = normalize(candidate).strip()
    if not normalized:
        return ""
    for match in ACT_REFERENCE_RE.finditer(normalized):
        if _valid_reference_match(match, normalized):
            return _canonical_act_match(match)
    return ""


def _act_reference(title: str, evidence: str) -> str:
    """Extrai e canoniza a identificação normativa compartilhada pelos backends."""
    candidates = [clean_text(evidence), clean_text(title)]

    for candidate in candidates:
        reference = _find_reference(normalize(candidate).strip()[:420])
        if reference:
            return reference

    for candidate in candidates:
        reference = _find_reference(candidate)
        if reference:
            return reference
    return "semantic:" + _canonical_semantic_title(title)


def _discriminating_tokens(title: str, evidence: str) -> frozenset[str]:
    semantic_title = _canonical_semantic_title(title)
    normalized = normalize(f"{semantic_title} {evidence}").strip()
    normalized = ACT_REFERENCE_RE.sub(" ", normalized)
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]{3,}", normalized)
        if token not in REFERENCE_NOISE and not token.isdigit()
    }
    return frozenset(tokens)


def reduced_reference_compatible(
    *,
    left_title: str,
    left_evidence: str,
    right_title: str,
    right_evidence: str,
) -> bool:
    left = _discriminating_tokens(left_title, left_evidence)
    right = _discriminating_tokens(right_title, right_evidence)
    if not left or not right:
        return False
    overlap = len(left & right)
    return overlap > 0 and overlap / min(len(left), len(right)) >= 0.75


def metadata_is_complete(*, source: str, edition: str, section: str, page: int | None) -> bool:
    source_norm = normalize(source).strip()
    if source_norm == "dou":
        return bool(clean_text(edition) and clean_text(section) and page is not None)
    return bool(clean_text(edition) and page is not None)


def backend_reference_key(
    *,
    source: str,
    category: str,
    published_at: str,
    title: str,
    evidence: str,
) -> str:
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
    """Alias do artigo; páginas do DODF permanecem identidades distintas."""
    source_norm = normalize(source).strip()
    category_norm = normalize(category).strip()
    parsed = urlsplit(link)
    canonical_link = urlunsplit(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.query, "")
    )
    if source_norm == "dodf":
        page_identity = parsed.fragment.casefold().strip()
        if not page_identity and page is not None:
            page_identity = f"page={page}"
        return sha256_text(
            source_norm,
            category_norm,
            published_at[:10],
            canonical_link,
            page_identity,
        )
    return sha256_text(source_norm, category_norm, published_at[:10], canonical_link)


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
    """Mantida apenas para leitura/migração externa; não autoriza substituição sozinha."""
    return sha256_text(
        normalize(source).strip(),
        normalize(category).strip(),
        published_at[:10],
        _canonical_edition(edition),
        _canonical_section(section),
        page if page is not None else "",
        _canonical_semantic_title(title),
    )
