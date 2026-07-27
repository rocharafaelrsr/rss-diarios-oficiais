from __future__ import annotations

import re
from datetime import datetime

from models import Document, FeedItem
from text_utils import clean_text, normalize

MAX_TITLE = 112
MAX_SUMMARY = 300


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
        if not needle:
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
    for right, (right_pos, right_group) in enumerate(events):
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


def _title_kind(title: str) -> str:
    value = normalize(title).strip()
    match = re.match(r"([a-z]+(?:\s+[a-z]+){0,2})", value)
    return match.group(1) if match else value


def strictly_relevant(category: str, source: str, title: str, text: str, next_year: int) -> bool:
    """Aplica o escopo material solicitado, independentemente de coincidências genéricas."""
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
                "concurso",
                "curso de formação",
                "candidato",
                "cadastro de reserva",
                "edital",
                "convoca",
                "nomea",
                "homologa",
                "resultado",
                "prorroga",
                "retifica",
                "inscrição",
            )
        )
        return marker and context

    ldo_marker = _has(norm, "lei de diretrizes orçamentárias") or _has(norm, "diretrizes orçamentárias") or _word(norm, "ldo")

    if category == "ldo":
        year_ok = _word(norm, str(next_year))
        legal_action = any(
            _has(norm, term)
            for term in (
                "dispõe sobre as diretrizes orçamentárias",
                "sanciona",
                "promulga",
                "publica a lei",
                "aprova a lei",
            )
        )
        return ldo_marker and year_ok and legal_action and _groups_near(
            norm,
            (
                ("lei de diretrizes orçamentárias", "diretrizes orçamentárias", " ldo "),
                (str(next_year),),
                ("lei", "sanciona", "promulga", "publica", "aprova"),
            ),
            800,
        )

    if category == "ldo_concursos":
        if _title_kind(title) in {
            "edital",
            "resultado",
            "portaria",
            "retificação",
            "retificacao",
            "aviso",
        }:
            return False
        personnel = (
            "concurso público",
            "provimento",
            "nomeação",
            "admissão de pessoal",
            "criação de cargos",
            "cargos vagos",
            "anexo de pessoal",
            "despesa de pessoal",
        )
        change = (
            "altera",
            "alteração",
            "inclui",
            "acrescenta",
            "suprime",
            "substitui",
            "retifica",
            "emenda",
            "veto",
        )
        legal = ("lei", "projeto de lei", "emenda", "veto", "mensagem")
        return ldo_marker and _groups_near(
            norm,
            (
                ("lei de diretrizes orçamentárias", "diretrizes orçamentárias", " ldo "),
                personnel,
                change,
                legal,
            ),
            900,
        )

    if category == "autorizacao_concurso":
        if _title_kind(title) in {
            "edital",
            "resultado",
            "retificação",
            "retificacao",
            "convocação",
            "convocacao",
            "homologação",
            "homologacao",
        }:
            return False
        patterns = (
            r"(?:fica\s+autorizad[ao]|autoriza(?:-se)?|autorizar)\s+(?:[^.;]{0,100}\s+)?(?:a\s+)?(?:realizacao|abertura)\s+(?:de|do)\s+(?:novo\s+)?(?:concurso\s+publico|certame)",
            r"(?:fica\s+autorizad[ao]|autoriza(?:-se)?|autorizar)\s+[^.;]{0,100}\s+a\s+realizar\s+(?:novo\s+)?concurso\s+publico",
        )
        return any(re.search(pattern, norm) for pattern in patterns)

    return False


def _dedupe_heading(text: str, title: str) -> str:
    value = clean_text(text)
    heading = clean_text(title)
    if not heading:
        return value
    while value.casefold().startswith(heading.casefold()):
        value = value[len(heading) :].lstrip(" -—:.;")
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


def _ldo_year(text: str, fallback: int | None = None) -> str:
    norm = normalize(text)
    years = re.findall(r"\b20\d{2}\b", norm)
    current = datetime.now().year
    plausible = [year for year in years if current - 1 <= int(year) <= current + 3]
    if plausible:
        return plausible[0]
    return str(fallback) if fallback else ""


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
            target = re.split(r",\s+(?:observad|conforme|nos termos|com vistas|mediante)\b", target, maxsplit=1, flags=re.I)[0]
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
        sentence = _operative_sentence(raw or combined, ("curso de formação", "convoca", "nomea", "prorroga", "homologa", "resultado", "retifica", "edital"))
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
        target = _authorization_target(combined, getattr(document, "organization", ""))
        action = f"Autoriza novo concurso para {target}" if target else "Autoriza a realização de novo concurso público"
        sentence = _operative_sentence(raw or combined, ("autoriza", "autorizada", "autorizar", "realização de concurso", "realizar concurso"))
        summary = sentence if sentence else action + "."

    else:
        action = clean_text(document.title)
        summary = _operative_sentence(raw or combined, tuple())

    title = _compact(f"[{prefix}] {action}", MAX_TITLE)
    summary = _compact(summary, MAX_SUMMARY)
    if normalize(summary).strip() == normalize(action).strip():
        summary = _compact(action + ". Consulte o ato oficial para os detalhes.", MAX_SUMMARY)
    return title, summary


def sanitize_stored_items(items: list[FeedItem], next_year: int) -> tuple[list[FeedItem], int]:
    output: list[FeedItem] = []
    removed = 0
    for item in items:
        if not strictly_relevant(item.category, item.source, item.title, item.excerpt, next_year):
            removed += 1
            continue
        document = Document(
            source=item.source,
            source_label=item.source_label,
            title=item.title,
            url=item.link,
            published_at=datetime.fromisoformat(item.published_at),
            text=item.excerpt,
            edition=item.edition,
            section=item.section,
            page=item.page,
        )
        item.title, item.excerpt = build_presentation(document, item.category, next_year)
        output.append(item)
    return output, removed
