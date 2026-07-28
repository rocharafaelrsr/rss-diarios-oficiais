from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from text_utils import clean_text, normalize


# Marcador interno removido por act_extraction.extract_matched_act antes de os
# termos correspondentes serem persistidos no FeedItem.
ACT_MATCH_SENTINEL = "\x00RSR_ACT\x00"

# A regra same_act reconhece os mesmos limites editoriais usados pelo extrator.
# EDITAL simples aceita número com ou sem marcador; EDITAL qualificado exige
# Nº/N°/N.º, usa até oito tokens e não atravessa pontuação.
ACT_MARKER_RE = re.compile(
    r"(?<!\w)(?:"
    r"(?:DECRETO(?:\s*[-–—]\s*|\s+)LEI|PROJETO\s+DE\s+LEI|"
    r"MEDIDA\s+PROVISÓRIA|INSTRUÇÃO\s+NORMATIVA|ORDEM\s+DE\s+SERVIÇO|"
    r"EMENDA|VETO|MENSAGEM|LEI|PORTARIA|DECRETO|RESOLUÇÃO|ATO|DESPACHO|AVISO)"
    r"\s+(?:N(?:\s*\.\s*)?[º°O]?\s*)?\d"
    r"|EDITAL\s+(?:N(?:\s*\.\s*)?[º°O]?\s*)?\d"
    r"|EDITAL(?:\s+[\wªº°-]+){1,8}\s+(?:[-–—]\s*)?N(?:\s*\.\s*)?[º°O]?\s*\d"
    r")",
    flags=re.I | re.U,
)
ACT_CITATION_PREFIX_RE = re.compile(
    r"(?:regid[oa]\s+pel[oa]|nos\s+termos\s+d[ao]|"
    r"conforme\s+(?:[oa]|dispost[oa]\s+n[ao]|previst[oa]\s+n[ao])|"
    r"em\s+conformidade\s+com\s+(?:[oa]|[oa]\s+dispost[oa]\s+n[ao])|"
    r"de\s+acordo\s+com\s+(?:[oa]|[oa]\s+dispost[oa]\s+n[ao])|"
    r"em\s+cumprimento\s+a[oa]?|em\s+atendimento\s+a[oa]?|"
    r"consoante\s+[oa]|em\s+observancia\s+(?:a|ao)|na\s+forma\s+d[ao]|"
    r"nos\s+moldes\s+d[ao]|previst[oa]\s+n[ao]|de\s+que\s+trata\s+[oa]|"
    r"referid[oa]\s+n[ao]|alterad[oa]\s+pel[oa]|com\s+fundamento\s+n[ao]|"
    r"por\s+meio\s+d[ao]|pel[oa]|objeto\s+d[ao]|referente\s+a[oa]?|"
    r"relativ[oa]\s+a[oa]?|retifica(?:\s+[oa])?|retificacao\s+d[ao])\s*$",
    flags=re.I,
)


def _act_markers(text: str) -> list[re.Match[str]]:
    markers: list[re.Match[str]] = []
    for marker in ACT_MARKER_RE.finditer(text):
        if marker.start() == 0:
            markers.append(marker)
            continue
        prefix = normalize(text[max(0, marker.start() - 180) : marker.start()]).strip()
        if ACT_CITATION_PREFIX_RE.search(prefix):
            continue
        markers.append(marker)
    return markers


def _split_acts(text: str) -> list[str]:
    """Divide uma página em atos prováveis, sem combinar atos adjacentes."""
    clean = clean_text(text)
    if not clean:
        return []
    markers = _act_markers(clean)
    if not markers:
        return [clean]

    acts: list[str] = []
    prefix = clean[: markers[0].start()].strip()
    if prefix:
        acts.append(prefix)
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(clean)
        act = clean[marker.start() : end].strip()
        if act:
            acts.append(act)
    return acts


@dataclass(slots=True)
class Rule:
    id: str
    label: str
    sources: set[str]
    priority: int
    max_span_chars: int | None = None
    same_act: bool = False
    any_phrases: list[str] = field(default_factory=list)
    unconditional_phrases: list[str] = field(default_factory=list)
    context_any: list[str] = field(default_factory=list)
    context_regex: list[str] = field(default_factory=list)
    all_groups: list[list[str]] = field(default_factory=list)
    any_regex: list[str] = field(default_factory=list)
    exclude_phrases: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Rule":
        span = data.get("max_span_chars")
        return cls(
            id=str(data["id"]),
            label=str(data["label"]),
            sources=set(data.get("sources", [])),
            priority=int(data.get("priority", 5)),
            max_span_chars=int(span) if span is not None else None,
            same_act=bool(data.get("same_act", False)),
            any_phrases=list(data.get("any_phrases", [])),
            unconditional_phrases=list(data.get("unconditional_phrases", [])),
            context_any=list(data.get("context_any", [])),
            context_regex=list(data.get("context_regex", [])),
            all_groups=[list(group) for group in data.get("all_groups", [])],
            any_regex=list(data.get("any_regex", [])),
            exclude_phrases=list(data.get("exclude_phrases", [])),
        )

    @staticmethod
    def _term_events(norm: str, group_id: int, terms: list[str]) -> list[tuple[int, int, str]]:
        events: list[tuple[int, int, str]] = []
        for term in terms:
            whole_term = term != term.strip()
            needle = normalize(term).strip()
            if not needle:
                continue
            if whole_term:
                pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
                for match in pattern.finditer(norm):
                    events.append((match.start(), group_id, term))
                continue
            start = 0
            while True:
                position = norm.find(needle, start)
                if position < 0:
                    break
                events.append((position, group_id, term))
                start = position + max(1, len(needle))
        return events

    @staticmethod
    def _minimum_cover(
        norm: str, groups: list[list[str]]
    ) -> tuple[int, list[str]] | None:
        events: list[tuple[int, int, str]] = []
        for group_id, terms in enumerate(groups):
            group_events = Rule._term_events(norm, group_id, terms)
            if not group_events:
                return None
            events.extend(group_events)
        events.sort(key=lambda event: event[0])

        counts: dict[int, int] = {}
        covered = 0
        left = 0
        best: tuple[int, int, list[str]] | None = None
        for right, (right_pos, right_group, _) in enumerate(events):
            counts[right_group] = counts.get(right_group, 0) + 1
            if counts[right_group] == 1:
                covered += 1
            while covered == len(groups) and left <= right:
                left_pos = events[left][0]
                span = right_pos - left_pos
                terms = list(dict.fromkeys(event[2] for event in events[left : right + 1]))
                if best is None or span < best[0]:
                    best = (span, left_pos, terms)
                left_group = events[left][1]
                counts[left_group] -= 1
                if counts[left_group] == 0:
                    covered -= 1
                left += 1
        if best is None:
            return None
        return best[0], best[2]

    def _context_terms(self, norm: str) -> list[str]:
        terms = list(self.context_any)
        for pattern in self.context_regex:
            for match in re.finditer(pattern, norm, flags=re.I | re.U):
                value = match.group(0).strip()
                if value:
                    terms.append(value)
        return terms

    def _match_one(self, text: str) -> list[str] | None:
        norm = normalize(text)
        if any(normalize(term).strip() in norm for term in self.exclude_phrases):
            return None

        unconditional = [term for term in self.unconditional_phrases if normalize(term).strip() in norm]
        if unconditional:
            return unconditional

        required_groups: list[list[str]] = []
        if self.any_phrases:
            required_groups.append(self.any_phrases)
        if self.context_any or self.context_regex:
            required_groups.append(self._context_terms(norm))
        required_groups.extend(self.all_groups)

        cover = self._minimum_cover(norm, required_groups) if required_groups else None
        if required_groups and cover is None:
            return None
        matched: list[str] = cover[1] if cover else []
        if cover and self.max_span_chars is not None and cover[0] > self.max_span_chars:
            return None

        if self.any_regex:
            regex_hits = [pattern for pattern in self.any_regex if re.search(pattern, text, flags=re.I | re.U)]
            if not required_groups and not regex_hits:
                return None
            matched.extend(regex_hits)

        return list(dict.fromkeys(matched)) if matched else None

    def match(self, source: str, text: str) -> list[str] | None:
        if self.sources and source not in self.sources:
            return None

        if not self.same_act:
            return self._match_one(text)

        # Exclusions, âncoras e distância são avaliadas dentro de cada ato. O ato
        # selecionado segue como marcador interno para o extrator, que o remove
        # antes de matched_terms ser persistido.
        for act in _split_acts(text):
            matched = self._match_one(act)
            if matched:
                return [ACT_MATCH_SENTINEL + act, *matched]
        return None
