from datetime import date, datetime

import main_dodf
from main import BRT
from models import Document


def test_disabled_dodf_skips_network_and_writes_current_status(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        main_dodf,
        "load_config",
        lambda _path: {
            "project": {"lookback_days": 3},
            "sources": {"dodf": {"enabled": False}},
        },
    )
    monkeypatch.setattr(main_dodf, "load_items", lambda _path: [])
    monkeypatch.setattr(
        main_dodf,
        "HttpClient",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("rede acionada")),
    )
    monkeypatch.setattr(main_dodf, "_write_status", lambda _root, status: captured.update(status))
    monkeypatch.setenv("RSS_RUN_ID", "run-disabled")
    monkeypatch.setattr("sys.argv", ["main_dodf.py", "--date", "2026-07-27"])

    assert main_dodf.main() == 0
    assert captured["run_id"] == "run-disabled"
    assert captured["sources"]["dodf"]["enabled"] is False
    assert captured["state_updated"] is False


def test_weekend_fallback_failure_does_not_skip_following_business_day(monkeypatch):
    calls: list[date] = []
    captured = {}

    class FakeCollector:
        backend = "dodf"
        fallback_reason = ""
        primary_attempts = 0
        primary_circuit_open = False
        primary_circuit_reason = ""
        primary_skipped_dates: list[str] = []

        def __init__(self, *_args, **_kwargs):
            pass

        def collect(self, day: date):
            calls.append(day)
            if day.weekday() >= 5:
                raise RuntimeError("falha local do SINJ no fim de semana")
            return [
                Document(
                    source="dodf",
                    source_label="Diário Oficial do Distrito Federal",
                    title="DODF 135 — página 1",
                    url="https://dodf.df.gov.br/arquivo.pdf#page=1",
                    published_at=datetime(2026, 7, 24, 6, tzinfo=BRT),
                    text="Conteúdo válido da edição de sexta-feira.",
                    edition="DODF 135",
                    page=1,
                )
            ]

    monkeypatch.setattr(
        main_dodf,
        "load_config",
        lambda _path: {
            "project": {
                "lookback_days": 3,
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
    monkeypatch.setattr("sys.argv", ["main_dodf.py", "--date", "2026-07-26", "--lookback", "3"])

    assert main_dodf.main() == 0
    assert calls == [date(2026, 7, 26), date(2026, 7, 25), date(2026, 7, 24)]
    assert captured["sources"]["dodf"]["documents_by_date"] == {
        "2026-07-26": None,
        "2026-07-25": None,
        "2026-07-24": 1,
    }
    assert captured["sources"]["dodf"]["healthy"] is True
    assert captured["state_updated"] is True


def test_status_helpers_reject_stale_status_and_partial_success_notice():
    status = {
        "run_id": "current-run",
        "sources": {"dodf": {"documents": 1}},
        "errors": [{"error": "uma data falhou"}],
        "state_updated": True,
    }

    assert main_dodf.status_belongs_to_run(status, "current-run") is True
    assert main_dodf.status_belongs_to_run(status, "old-run") is False
    assert main_dodf.invalid_collection(status) is False

    status["sources"]["dodf"]["documents"] = 0
    status["state_updated"] = False
    assert main_dodf.invalid_collection(status) is True
