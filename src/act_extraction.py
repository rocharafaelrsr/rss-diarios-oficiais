from __future__ import annotations

from presentation import MAX_EVIDENCE, _compact, _minimum_term_window
from rules import ACT_MATCH_SENTINEL, ACT_MARKER_RE, ACT_CITATION_PREFIX_RE
from text_utils import clean_text, normalize


def _act_markers(text: str):
    """Retorna cabeçalhos prováveis, excluindo atos apenas citados no corpo."""
    markers = []
    for marker in ACT_MARKER_RE.finditer(text):
        if marker.start() == 0:
            markers.append(marker)
            continue
        prefix = normalize(text[max(0, marker.start() - 180) : marker.start()]).strip()
        if ACT_CITATION_PREFIX_RE.search(prefix):
            continue
        markers.append(marker)
    return markers


def _compact_around_matches(text: str, matched_terms: list[str]) -> str:
    clean = clean_text(text)
    if len(clean) <= MAX_EVIDENCE:
        return clean
    norm = normalize(clean).strip()
    window = _minimum_term_window(norm, matched_terms)
    if window is None:
        return _compact(clean, MAX_EVIDENCE)
    center = max(0, min(len(clean), (window[0] + window[1]) // 2))
    radius = MAX_EVIDENCE // 2
    start = max(0, center - radius)
    end = min(len(clean), start + MAX_EVIDENCE)
    if end == len(clean):
        start = max(0, end - MAX_EVIDENCE)
    snippet = clean[start:end].strip()
    if start > 0:
        snippet = "… " + snippet
    if end < len(clean):
        snippet += " …"
    return snippet


def extract_matched_act(text: str, matched_terms: list[str]) -> str:
    """Recorta o ato correspondente sem perder cabeçalhos compostos."""
    # Regras com same_act já selecionaram o ato exato. O marcador é transitório:
    # removê-lo da lista impede que o conteúdo inteiro seja salvo em matched_terms.
    for index, term in enumerate(list(matched_terms)):
        if term.startswith(ACT_MATCH_SENTINEL):
            act = clean_text(term[len(ACT_MATCH_SENTINEL) :])
            del matched_terms[index]
            return _compact_around_matches(act, matched_terms)

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

    return _compact_around_matches(act or clean, matched_terms)
