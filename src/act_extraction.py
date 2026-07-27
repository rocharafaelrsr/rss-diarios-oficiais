from __future__ import annotations

import re

from presentation import (
    ACT_CITATION_PREFIX_RE,
    MAX_EVIDENCE,
    _compact,
    _minimum_term_window,
)
from text_utils import clean_text, normalize

# Tipos compostos devem vir antes de LEI/DECRETO para que o início do ato não
# seja deslocado para a palavra interna. Inclui também os atos monitorados pela
# regra de alterações da LDO.
ACT_MARKER_RE = re.compile(
    r"(?<!\w)(?:DECRETO(?:\s*[-–—]\s*|\s+)LEI|PROJETO\s+DE\s+LEI|"
    r"MEDIDA\s+PROVISÓRIA|INSTRUÇÃO\s+NORMATIVA|ORDEM\s+DE\s+SERVIÇO|"
    r"EMENDA|VETO|MENSAGEM|LEI|PORTARIA|EDITAL|DECRETO|RESOLUÇÃO|"
    r"ATO|DESPACHO|AVISO)\s+(?:N[º°O]?\s*)?\d",
    flags=re.I | re.U,
)


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
    """Recorta o ato correspondente sem perder cabeçalhos compostos."""
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
