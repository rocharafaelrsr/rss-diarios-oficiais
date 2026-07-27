from datetime import date
from types import SimpleNamespace

import requests

from diarios.dodf_resilient import ResilientDodfCollector
from main_dodf import dodf_business_day_health


class FakeClient:
    def __init__(self):
        self.session = SimpleNamespace(headers={"User-Agent": "test"})

    def get(self, *_args, **_kwargs):
        raise AssertionError("client.get não deveria ser chamado neste teste")


def test_connect_timeout_opens_circuit_for_remaining_dates(monkeypatch):
    calls: list[str] = []

    def fail(url, **_kwargs):
        calls.append(url)
        raise requests.ConnectTimeout("timeout")

    monkeypatch.setattr(requests, "get", fail)
    collector = ResilientDodfCollector(
        FakeClient(),
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
    )
    collector._collect_sinj = lambda _day: []

    assert collector.collect(date(2026, 7, 27)) == []
    assert collector.primary_circuit_open is True
    assert collector.primary_attempts == 1

    assert collector.collect(date(2026, 7, 24)) == []
    assert collector.primary_attempts == 1
    assert collector.primary_skipped_dates == ["2026-07-24"]
    assert len(calls) == 1


def test_weekend_goes_directly_to_sinj(monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("portal primário consultado")),
    )
    collector = ResilientDodfCollector(
        FakeClient(),
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
    )
    collector._collect_sinj = lambda _day: ["documento"]

    assert collector.collect(date(2026, 7, 26)) == ["documento"]
    assert collector.primary_attempts == 0
    assert collector.primary_skipped_dates == ["2026-07-26"]
    assert collector.backend == "sinj"


def test_primary_listing_uses_one_fast_request_without_warmup(monkeypatch):
    calls: list[tuple[str, object]] = []

    class Response:
        url = "https://dodf.df.gov.br/dodf/jornal/diario?data=1"
        text = '''
        <a href="/dodf/jornal/visualizar-pdf?arquivo=DODF+135.pdf">PDF</a>
        <a href="https://evil.example/visualizar-pdf?arquivo=x.pdf">Externo</a>
        '''

        def raise_for_status(self):
            return None

    def success(url, **kwargs):
        calls.append((url, kwargs.get("timeout")))
        return Response()

    monkeypatch.setattr(requests, "get", success)
    collector = ResilientDodfCollector(
        FakeClient(),
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
    )

    urls = collector.list_pdf_urls(date(2026, 7, 24))
    assert urls == [
        "https://dodf.df.gov.br/dodf/jornal/visualizar-pdf?arquivo=DODF+135.pdf"
    ]
    assert calls == [
        ("https://www.dodf.df.gov.br/dodf/jornal/diario", (3, 10))
    ]
    assert collector.primary_attempts == 1


def test_business_day_health_rejects_all_zero_documents():
    days = [
        date(2026, 7, 27),
        date(2026, 7, 26),
        date(2026, 7, 25),
        date(2026, 7, 24),
        date(2026, 7, 23),
    ]
    health = dodf_business_day_health(
        days,
        {day.isoformat(): 0 for day in days},
    )
    assert health["healthy"] is False
    assert health["business_days_checked"] == [
        "2026-07-27",
        "2026-07-24",
        "2026-07-23",
    ]
    assert health["business_days_with_documents"] == []


def test_business_day_health_accepts_one_valid_edition():
    days = [date(2026, 7, 27), date(2026, 7, 26), date(2026, 7, 24)]
    health = dodf_business_day_health(
        days,
        {
            "2026-07-27": 0,
            "2026-07-26": 0,
            "2026-07-24": 98,
        },
    )
    assert health["healthy"] is True
    assert health["business_days_with_documents"] == ["2026-07-24"]


def test_weekend_only_window_is_not_declared_unhealthy():
    days = [date(2026, 7, 26), date(2026, 7, 25)]
    health = dodf_business_day_health(
        days,
        {"2026-07-26": 0, "2026-07-25": 0},
    )
    assert health["healthy"] is True
    assert health["business_days_checked"] == []
