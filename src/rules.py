from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from text_utils import normalize


@dataclass(slots=True)
class Rule:
    id: str
    label: str
    sources: set[str]
    priority: int
    max_span_chars: int | None = None
    any_phrases: list[str] = field(default_factory=list)
    unconditional_phrases: list[str] = field(default_factory=list)
    context_any: list[str] = field(default_factory=list)
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
            any_phrases=list(data.get("any_phrases", [])),
            unconditional_phrases=list(data.get("unconditional_phrases", [])),
            context_any=list(data.get("context_any", [])),
            all_groups=[list(group) for group in data.get("all_groups", [])],
            any_regex=list(data.get("any_regex", [])),
            exclude_phrases=list(data.get("exclude_phrases", [])),
        )

    @staticmethod
    def _term_events(norm: str, group_id: int, terms: list[str]) -> list[tuple[int, int, str]]:
        events: list[tuple[int, int, str]] = []
        for term in terms:
            needle = normalize(term).strip()
            if not needle:
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

    def match(self, source: str, text: str) -> list[str] | None:
        if self.sources and source not in self.sources:
            return None
        norm = normalize(text)
        if any(normalize(term) in norm for term in self.exclude_phrases):
            return None

        unconditional = [term for term in self.unconditional_phrases if normalize(term) in norm]
        if unconditional:
            return unconditional

        required_groups: list[list[str]] = []
        if self.any_phrases:
            required_groups.append(self.any_phrases)
        if self.context_any:
            required_groups.append(self.context_any)
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
