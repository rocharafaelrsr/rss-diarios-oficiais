from datetime import date
from types import SimpleNamespace

import requests

import diarios.dodf_resilient as dodf_resilient
from diarios.dodf_resilient import ResilientDodfCollector


class FakeClient:
    def __init__(self):
        self.session = SimpleNamespace(headers={"User-Agent": "test"})

    def get(self, *_args, **_kwargs):
        raise AssertionError("get deve ser substituído no teste")


def test_partial_pdf_failure_does_not_open_primary_circuit(monkeypatch):
    collector = ResilientDodfCollector(
        FakeClient(),
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
    )
    pdf_urls = [
        "https://dodf.df.gov.br/dodf/jornal/visualizar-pdf?arquivo=DODF+135-A.pdf",
        "https://dodf.df.gov.br/dodf/jornal/visualizar-pdf?arquivo=DODF+135-B.pdf",
    ]
    monkeypatch.setattr(collector, "list_pdf_urls", lambda _day: pdf_urls)

    class Response:
        content = b"%PDF-blank"

    def mixed_download(url, **_kwargs):
        if url == pdf_urls[0]:
            return Response()
        raise requests.ConnectTimeout("segundo PDF indisponível")

    monkeypatch.setattr(collector.client, "get", mixed_download)

    class BlankPage:
        def get_text(self, _mode):
            return ""

    class BlankPdf:
        def __iter__(self):
            return iter([BlankPage()])

        def close(self):
            return None

    monkeypatch.setattr(
        dodf_resilient.fitz,
        "open",
        lambda *_args, **_kwargs: BlankPdf(),
    )
    collector._collect_sinj = lambda _day: []

    assert collector.collect(date(2026, 7, 27)) == []
    assert collector.primary_circuit_open is False
    assert collector.fallback_reason == "endpoint primário sem documentos"


def test_page_extraction_failure_does_not_skip_later_valid_pdf(monkeypatch):
    collector = ResilientDodfCollector(
        FakeClient(),
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
    )
    pdf_urls = [
        "https://dodf.df.gov.br/dodf/jornal/visualizar-pdf?arquivo=DODF+136-A.pdf",
        "https://dodf.df.gov.br/dodf/jornal/visualizar-pdf?arquivo=DODF+136-B.pdf",
    ]
    monkeypatch.setattr(collector, "list_pdf_urls", lambda _day: pdf_urls)

    class Response:
        content = b"%PDF-test"

    monkeypatch.setattr(collector.client, "get", lambda *_args, **_kwargs: Response())

    class BrokenPage:
        def get_text(self, _mode):
            raise RuntimeError("página malformada")

    class ValidPage:
        def get_text(self, _mode):
            return "PORTARIA Nº 10. Conteúdo válido do segundo PDF."

    class FakePdf:
        def __init__(self, pages):
            self.pages = pages

        def __iter__(self):
            return iter(self.pages)

        def close(self):
            return None

    opened = 0

    def open_pdf(*_args, **_kwargs):
        nonlocal opened
        opened += 1
        if opened == 1:
            return FakePdf([BrokenPage()])
        return FakePdf([ValidPage()])

    monkeypatch.setattr(dodf_resilient.fitz, "open", open_pdf)
    collector._collect_sinj = lambda _day: (_ for _ in ()).throw(
        AssertionError("fallback não deveria ser necessário")
    )

    documents = collector.collect(date(2026, 7, 27))

    assert opened == 2
    assert len(documents) == 1
    assert documents[0].url.endswith("DODF+136-B.pdf#page=1")
    assert collector.primary_circuit_open is False
