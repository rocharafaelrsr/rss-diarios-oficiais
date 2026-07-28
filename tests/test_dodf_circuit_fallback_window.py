from datetime import date, datetime

import main_dodf
from main import BRT
from models import Document


def test_open_circuit_does_not_stop_fallbacks_for_older_dates(monkeypatch):
    calls: list[date] = []
    captured = {}

    class FakeCollector:
        backend = "sinj"
        fallback_reason = ""
        primary_attempts = 1
        primary_circuit_open = False
        primary_circuit_reason = ""
        primary_skipped_dates: list[str] = []

        def __init__(self, *_args, **_kwargs):
            pass

        def collect(self, day: date):
            calls.append(day)
            if day == date(2026, 7, 27):
                self.primary_circuit_open = True
                self.primary_circuit_reason = "PDF primário indisponível"
                raise RuntimeError("SINJ falhou apenas para a data mais recente")
            if day.weekday() >= 5:
                self.primary_skipped_dates.append(day.isoformat())
                raise RuntimeError("SINJ falhou apenas neste fim de semana")
            return [
                Document(
                    source="dodf",
                    source_label="Diário Oficial do Distrito Federal",
                    title="DODF 135 — página 1",
                    url="https://sinj.df.gov.br/arquivo-sexta.pdf#page=1",
                    published_at=datetime(2026, 7, 24, 6, tzinfo=BRT),
                    text="Conteúdo válido recuperado para a sexta-feira anterior.",
                    edition="DODF 135",
                    page=1,
                )
            ]

    monkeypatch.setattr(
        main_dodf,
        "load_config",
        lambda _path: {
            "project": {
                "lookback_days": 4,
                "request_timeout_seconds": 35,
                "user_agent": "test",
                "retention_days": 730,
                "base_url": "https://example.test",
                "max_items_per_feed": 300,
            },
            "sources": {
                "dodf": {
                    "enabled": True,
                    "required": True,
                    "daily_url": "https://dodf.df.gov.br/dodf/jornal/diario",
                }
            },
            "rules": [],
            "feeds": {},
        },
    )
    monkeypatch.setattr(main_dodf, "HttpClient", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(main_dodf, "ResilientDodfCollector", FakeCollector)
    monkeypatch.setattr(main_dodf, "load_items", lambda _path: [])
    monkeypatch.setattr(main_dodf, "classify", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(main_dodf, "sanitize_stored_items", lambda items, _year: (items, 0))
    monkeypatch.setattr(main_dodf, "merge_items", lambda old, new, **_kwargs: old + new)
    monkeypatch.setattr(main_dodf, "save_items", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(main_dodf, "_write_status", lambda _root, status: captured.update(status))
    monkeypatch.setattr(
        "sys.argv",
        ["main_dodf.py", "--date", "2026-07-27", "--lookback", "4"],
    )

    assert main_dodf.main() == 0
    assert calls == [
        date(2026, 7, 27),
        date(2026, 7, 26),
        date(2026, 7, 25),
        date(2026, 7, 24),
    ]
    assert captured["sources"]["dodf"]["documents_by_date"] == {
        "2026-07-27": None,
        "2026-07-26": None,
        "2026-07-25": None,
        "2026-07-24": 1,
    }
    assert captured["sources"]["dodf"]["healthy"] is True
    assert captured["state_updated"] is True
