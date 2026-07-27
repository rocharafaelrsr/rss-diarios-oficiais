from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from models import Document, FeedItem
from text_utils import clean_text, normalize, sha256_text

MAX_TITLE = 112
MAX_SUMMARY = 300
MAX_EVIDENCE = 2800
ACT_MARKER_RE = re.compile(
    r"(?<!\w)(?:LEI|PORTARIA|EDITAL|DECRETO|RESOLUÇÃO|INSTRUÇÃO\s+NORMATIVA|"
    r"ATO|DESPACHO|ORDEM\s+DE\s+SERVIÇO|AVISO)\s+(?:N[º°O]?\s*)?\d",
    flags=re.I | re.U,
)
ACT_CITATION_PREFIX_RE = re.compile(
    r"(?:regid[oa]\s+pel[oa]|nos\s+termos\s+d[ao]|"
    r"conforme\s+(?:[oa]|dispost[oa]\s+n[ao]|previst[oa]\s+n[ao])|"
    r"em\s+conformidade\s+com\s+(?:[oa]|[oa]\s+dispost[oa]\s+n[ao])|"
    r"de\s+acordo\s+com\s+(?:[oa]|[oa]\s+dispost[oa]\s+n[ao])|"
    r"consoante\s+[oa]|em\s+observancia\s+(?:a|ao)|na\s+forma\s+d[ao]|"
    r"nos\s+moldes\s+d[ao]|previst[oa]\s+n[ao]|de\s+que\s+trata\s+[oa]|"
    r"referid[oa]\s+n[ao]|alterad[oa]\s+pel[oa]|com\s+fundamento\s+n[ao]|"
    r"por\s+meio\s+d[ao]|pel[oa])\s*$",
    flags=re.I,
)


def _compact(text: str, limit: int) -> str:
    value = clean_text(text).strip(" .;:-")
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def _has(norm: str, phrase: str) -> bool:
    return normalize(phrase).strip() in norm


def _word(norm: str, word: str) -> bool:
    needle = normalize(word).strip()
    return bool(needle and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", norm))


def _events(norm: str, terms: tuple[str, ...]) -> list[int]:
    positions: list[int] = []
    for term in terms:
        needle = normalize(term).strip()
        if not needle or "\\" in needle:
            continue
        start = 0
        while True:
            pos = norm.find(needle, start)
            if pos < 0:
                break
            positions.append(pos)
            start = pos + max(1, len(needle))
    return positions


def _groups_near(norm: str, groups: tuple[tuple[str, ...], ...], max_span: int) -> bool:
    grouped = [_events(norm, group) for group in groups]
    if any(not positions for positions in grouped):
        return False
    events = sorted((pos, group_id) for group_id, positions in enumerate(grouped) for pos in positions)
    counts: dict[int, int] = {}
    covered = 0
    left = 0
    for right_pos, right_group in events:
        counts[right_group] = counts.get(right_group, 0) + 1
        if counts[right_group] == 1:
            covered += 1
        while covered == len(groups):
            left_pos, left_group = events[left]
            if right_pos - left_pos <= max_span:
                return True
            counts[left_group] -= 1
            if counts[left_group] == 0:
                covered -= 1
            left += 1
    return False


def _minimum_term_window(norm: str, terms: list[str]) -> tuple[int, int] | None:
    groups: list[list[int]] = []
    for term in dict.fromkeys(terms):
        positions = _events(norm, (term,))
        if positions:
            groups.append(positions)
    if not groups:
        return None
    events = sorted((pos, group_id) for group_id, positions in enumerate(groups) for pos in positions)
    counts: dict[int, int] = {}
    covered = 0
    left = 0
    best: tuple[int, int] | None = None
    for right_pos, right_group in events:
        counts[right_group] = counts.get(right_group, 0) + 1
        if counts[right_group] == 1:
            covered += 1
        while covered == len(groups):
            left_pos, left_group = events[left]
            if best is None or right_pos - left_pos < best[1] - best[0]:
                best = (left_pos, right_pos)
            counts[left_group] -= 1
            if counts[left_group] == 0:
                covered -= 1
            left += 1
    return best


def _act_markers(text: str) -> list[re.Match[str]]:
    """Retorna cabeçalhos prováveis, excluindo atos apenas citados no corpo."""
    markers: list[re.Match[str]] = []
    for marker in ACT_MARKER_RE.finditer(text):
        if marker.start() == 0:
            markers.append(marker)
            continue
        prefix = normalize(text[max(0, marker.start() - 160) : marker.start()]).strip()
        if ACT_CITATION_PREFIX_RE.search(prefix):
            continue
        markers.append(marker)
    return markers


def extract_matched_act(text: str, matched_terms: list[str]) -> str:
    """Recorta o ato que contém o conjunto de termos, evitando outros atos da página."""
    clean = clean_text(text)
    if not clean:
        return ""
    norm = normalize(clean).strip()
    window = _minimum_term_window(norm, matched_terms)
    if window is None:
        return _compact(clean, MAX_EVIDENCE)
    center = max(0, min(len(clean), (window[0] + window[1]) // 2))

    markers = _act_markers(clean)
    start = 0
    end = len(clean)
    for index, marker in enumerate(markers):
        if marker.start() <= center:
            start = marker.start()
            end = markers[index + 1].start() if index + 1 < len(markers) else len(clean)
        else:
            break
    act = clean[start:end].strip()
    if 80 <= len(act) <= MAX_EVIDENCE:
        return act

    radius = MAX_EVIDENCE // 2
    start = max(0, center - radius)
    end = min(len(clean), center + radius)
    return clean[start:end].strip()


def _title_starts(title: str, words: tuple[str, ...]) -> bool:
    value = normalize(title).strip()
    return any(value.startswith(normalize(word).strip()) for word in words)


def _ldo_marker(norm: str) -> bool:
    return any(
        _has(norm, phrase)
        for phrase in (
            "lei de diretrizes orçamentárias",
            "diretrizes orçamentárias",
            "diretrizes para a elaboração e a execução da lei orçamentária",
            "diretrizes para elaboração e execução da lei orçamentária",
        )
    ) or _word(norm, "ldo")


def _authorization_matches(norm: str) -> list[re.Match[str]]:
    pattern = re.compile(
        r"(?:fica\s+autorizad[ao]|autoriza(?:-se)?|autorizar)\b"
        r"[^.;]{0,220}?\b(?:realizar|realizacao|abertura)\b"
        r"[^.;]{0,120}?\b(?:concurso\s+publico|certame)\b"
    )
    return list(pattern.finditer(norm))


def _is_negated_authorization(norm: str, match: re.Match[str]) -> bool:
    before_and_clause = norm[max(0, match.start() - 100) : match.end()]
    clause = match.group(0)
    negation_before_verb = re.search(
        r"\b(?:nao|jamais|vedad[oa]|deixa\s+de|sem)\b[^.;]{0,60}"
        r"\b(?:autoriza|autorizar|autorizad[ao])\b",
        before_and_clause,
    )
    # Só considera negação ligada diretamente à ação. Cláusulas restritivas como
    # “sem aumento de despesa, a realizar concurso” continuam válidas.
    negation_before_action = re.search(
        r"\b(?:nao|jamais|sem)\s+(?:a\s+)?(?:proceder\s+a\s+)?"
        r"(?:realizar|realizacao|abertura)\b",
        clause,
    )
    return bool(negation_before_verb or negation_before_action)


def strictly_relevant(category: str, source: str, title: str, text: str, next_year: int) -> bool:
    combined = clean_text(f"{title}\n{text}")
    norm = normalize(combined)

    if category == "atub":
        if source != "dodf":
            return False
        marker = any(
            _has(norm, phrase)
            for phrase in (
                "auditor fiscal de atividades urbanas",
                "auditor de atividades urbanas",
                "auditoria de atividades urbanas",
                "carreira auditoria de atividades urbanas",
                "edital nº 01/2022",
                "edital n° 01/2022",
            )
        ) or _word(norm, "atub")
        context = any(
            _has(norm, term)
            for term in (
                "concurso", "curso de formação", "candidato", "cadastro de reserva",
                "edital", "convoca", "nomea", "homologa", "resultado", "prorroga",
                "retifica", "inscrição",
            )
        )
        return marker and context

    if category == "ldo":
        year_ok = _ldo_year(combined, next_year) == str(next_year)
        enactment = _title_starts(title, ("lei",)) or any(
            _has(norm, term)
            for term in (
                "dispõe sobre as diretrizes",
                "estabelece as diretrizes orçamentárias",
                "estabelece as diretrizes para a elaboração",
                "eu sanciono",
                "sanciono",
                "promulga",
            )
        )
        return _ldo_marker(norm) and year_ok and enactment

    if category == "ldo_concursos":
        if _title_starts(title, ("edital", "resultado", "portaria", "retificação", "aviso")):
            return False
        personnel = (
            "concurso público", "provimento", "nomeação", "admissão de pessoal",
            "criação de cargos", "cargos vagos", "anexo de pessoal", "despesa de pessoal",
        )
        change = (
            "altera", "alteração", "inclui", "acrescenta", "suprime", "substitui",
            "retifica", "emenda", "veto",
        )
        legal = ("lei", "projeto de lei", "emenda", "veto", "mensagem")
        return _ldo_marker(norm) and _groups_near(
            norm,
            (
                (
                    "lei de diretrizes orçamentárias", "diretrizes orçamentárias", " ldo ",
                    "diretrizes para a elaboração e a execução da lei orçamentária",
                ),
                personnel, change, legal,
            ),
            900,
        )

    if category == "autorizacao_concurso":
        if _title_starts(title, ("edital", "resultado", "retificação", "convocação", "homologação")):
            return False
        matches = _authorization_matches(norm)
        return any(not _is_negated_authorization(norm, match) for match in matches)

    return False


def _dedupe_heading(text: str, title: str) -> str:
    value = clean_text(text)
    heading = clean_text(title)
    if not heading:
        return value
    while value.casefold().startswith(heading.casefold()):
        value = value[len(heading):].lstrip(" -—:.;")
    return value


def _sentences(text: str) -> list[str]:
    value = clean_text(text)
    parts = re.split(r"(?<=[.;!?])\s+(?=[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ0-9])", value)
    return [clean_text(part) for part in parts if len(clean_text(part)) >= 24]


def _operative_sentence(text: str, needles: tuple[str, ...]) -> str:
    sentences = _sentences(text)
    for sentence in sentences:
        norm = normalize(sentence)
        if any(_has(norm, needle) for needle in needles):
            return sentence
    return sentences[0] if sentences else clean_text(text)


def _ldo_year(text: str, preferred: int | None = None) -> str:
    norm = normalize(text)
    # Primeiro, associa o ano à própria LDO ou Lei Orçamentária. Referências
    # posteriores a outros exercícios (resultados, metas ou séries históricas)
    # não podem substituir o exercício principal.
    specific_patterns = (
        r"(?:lei\s+de\s+diretrizes\s+orcamentarias|\bldo\b)[^.;]{0,180}?"
        r"(?:para|relativ[ao]s?\s+(?:a|ao)|do)\s+(?:o\s+exercicio\s+de\s+)?(20\d{2})",
        r"diretrizes[^.;]{0,220}?lei\s+orcamentaria(?:\s+anual)?[^.;]{0,100}?"
        r"(?:para\s+o\s+exercicio\s+de|do\s+exercicio\s+de|de|para)\s+(20\d{2})",
        r"lei\s+orcamentaria(?:\s+anual)?[^.;]{0,120}?"
        r"(?:para\s+o\s+exercicio\s+de|do\s+exercicio\s+de|de|para)\s+(20\d{2})",
        r"diretrizes[^.;]{0,160}?\bpara\s+(?:o\s+exercicio\s+de\s+)?(20\d{2})",
        r"\bldo\s+(?:de|para)\s+(20\d{2})",
    )
    for pattern in specific_patterns:
        match = re.search(pattern, norm)
        if match:
            return match.group(1)

    generic_matches = list(
        re.finditer(
            r"(?:para\s+o\s+exercicio|exercicio|ano\s+financeiro)\s+(?:de\s+)?(20\d{2})",
            norm,
        )
    )
    for match in generic_matches:
        context = norm[max(0, match.start() - 220) : min(len(norm), match.end() + 80)]
        if _ldo_marker(context) or "lei orcamentaria" in context:
            return match.group(1)

    if preferred is not None and _word(norm, str(preferred)):
        return str(preferred)

    generic_years = list(dict.fromkeys(match.group(1) for match in generic_matches))
    if len(generic_years) == 1:
        return generic_years[0]
    return str(preferred) if preferred is not None else ""


def _authorization_target(text: str, organization: str = "") -> str:
    value = clean_text(text)
    patterns = (
        r"concurso\s+público\s+(?:destinado\s+)?para\s+(?:o\s+provimento\s+de\s+)?([^.;]{8,150})",
        r"realização\s+de\s+(?:novo\s+)?concurso\s+público\s+(?:destinado\s+)?para\s+([^.;]{8,150})",
        r"realizar\s+(?:novo\s+)?concurso\s+público\s+para\s+([^.;]{8,150})",
    )
    for pattern in patterns:
        match = re.search(pattern, value, flags=re.I | re.U)
        if match:
            target = clean_text(match.group(1))
            target = re.split(
                r",\s+(?:observad|conforme|nos termos|com vistas|mediante)\b",
                target,
                maxsplit=1,
                flags=re.I,
            )[0]
            return _compact(target, 78)
    org = clean_text(organization)
    if org:
        org = org.split("/")[-1].strip()
        return _compact(org, 72)
    return ""


def build_presentation(document: Document, category: str, next_year: int) -> tuple[str, str]:
    prefix = "DODF" if document.source == "dodf" else "DOU"
    raw = _dedupe_heading(document.text, document.title)
    combined = clean_text(f"{document.title}. {raw}")
    norm = normalize(combined)

    if category == "atub":
        if _has(norm, "curso de formação") and _has(norm, "convoca"):
            action = "Convoca candidatos do concurso ATUB para o curso de formação"
        elif _has(norm, "nomea"):
            action = "Nomeia aprovados no concurso ATUB"
        elif _has(norm, "prorroga") and _has(norm, "validade"):
            action = "Prorroga a validade do concurso ATUB"
        elif _has(norm, "homologa") and _has(norm, "resultado"):
            action = "Homologa o resultado do concurso ATUB"
        elif _has(norm, "resultado"):
            action = "Publica resultado do concurso ATUB"
        elif _has(norm, "retifica"):
            action = "Retifica ato do concurso ATUB"
        elif _has(norm, "convoca") or _has(norm, "chamamento"):
            action = "Convoca candidatos do concurso ATUB"
        elif _has(norm, "edital") or _has(norm, "inscrição"):
            action = "Publica edital do concurso ATUB"
        else:
            action = "Publica ato relativo ao concurso ATUB"
        sentence = _operative_sentence(
            raw or combined,
            ("curso de formação", "convoca", "nomea", "prorroga", "homologa", "resultado", "retifica", "edital"),
        )
        summary = sentence if sentence else action + "."
    elif category == "ldo":
        year = _ldo_year(combined, next_year)
        jurisdiction = "federal" if document.source == "dou" else "do Distrito Federal"
        action = f"Publica a LDO {jurisdiction} de {year}" if year else f"Publica a LDO {jurisdiction}"
        act = clean_text(document.title)
        if act and len(act) <= 90 and re.search(r"\blei\b", act, flags=re.I):
            summary = f"{act} estabelece as diretrizes orçamentárias {jurisdiction} para {year}."
        else:
            summary = f"A publicação estabelece as diretrizes orçamentárias {jurisdiction} para {year}."
    elif category == "ldo_concursos":
        year = _ldo_year(combined)
        suffix = f" de {year}" if year else ""
        if _has(norm, "veto"):
            action = f"Veta dispositivo da LDO{suffix} sobre concursos"
        elif _has(norm, "retifica"):
            action = f"Retifica a LDO{suffix} em matéria de concursos"
        elif _has(norm, "inclui") or _has(norm, "acrescenta"):
            action = f"Inclui previsão de concursos na LDO{suffix}"
        else:
            action = f"Altera a LDO{suffix} quanto a concursos e provimentos"
        summary = f"A publicação modifica a LDO{suffix} em dispositivos relativos a concursos, provimentos, cargos ou admissões de pessoal."
    elif category == "autorizacao_concurso":
        target = _authorization_target(combined, document.organization)
        action = f"Autoriza novo concurso para {target}" if target else "Autoriza a realização de novo concurso público"
        sentence = _operative_sentence(
            raw or combined,
            ("autoriza", "autorizada", "autorizar", "realização de concurso", "realizar concurso"),
        )
        summary = sentence if sentence else action + "."
    else:
        action = clean_text(document.title)
        summary = _operative_sentence(raw or combined, tuple())

    title = _compact(f"[{prefix}] {action}", MAX_TITLE)
    summary = _compact(summary, MAX_SUMMARY)
    if normalize(summary).strip() == normalize(action).strip():
        summary = _compact(action + ". Consulte o ato oficial para os detalhes.", MAX_SUMMARY)
    return title, summary


def stable_identity(
    *,
    source: str,
    category: str,
    published_at: str,
    edition: str,
    section: str,
    page: int | None,
    evidence: str,
) -> str:
    return sha256_text(
        source,
        category,
        published_at[:10],
        edition,
        section,
        page or "",
        normalize(evidence).strip(),
    )


def recollection_key(
    *,
    source: str,
    category: str,
    published_at: str,
    link: str,
    page: int | None,
) -> str:
    parsed = urlsplit(link)
    canonical_link = urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.query, ""))
    return sha256_text(source, category, published_at[:10], canonical_link, page or "")


def sanitize_stored_items(items: list[FeedItem], next_year: int) -> tuple[list[FeedItem], int]:
    output: list[FeedItem] = []
    removed = 0
    for item in items:
        evidence = clean_text(item.evidence)
        semantic = item.title.startswith("[DODF]") or item.title.startswith("[DOU]")
        item.recollection_key = item.recollection_key or recollection_key(
            source=item.source,
            category=item.category,
            published_at=item.published_at,
            link=item.link,
            page=item.page,
        )

        if not evidence and semantic:
            # Preserva o item legado fora do lookback. Quando o mesmo link/página
            # for recolhido, merge_items o substituirá usando recollection_key.
            item.identity = item.identity or item.guid
            output.append(item)
            continue

        evidence = evidence or clean_text(item.excerpt)
        if not strictly_relevant(item.category, item.source, item.title, evidence, next_year):
            removed += 1
            continue

        document = Document(
            source=item.source,
            source_label=item.source_label,
            title=item.title,
            url=item.link,
            published_at=datetime.fromisoformat(item.published_at),
            text=evidence,
            edition=item.edition,
            section=item.section,
            page=item.page,
        )
        item.title, item.excerpt = build_presentation(document, item.category, next_year)
        item.evidence = evidence
        item.identity = stable_identity(
            source=item.source,
            category=item.category,
            published_at=item.published_at,
            edition=item.edition,
            section=item.section,
            page=item.page,
            evidence=evidence,
        )
        item.guid = item.identity
        output.append(item)
    return output, removed
