from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import requests

from diarios.dodf import DodfCollector
from diarios.dodf_resilient import ResilientDodfCollector

KNOWN_24_JULY_ID = "d00d5df2-c3f3-3101-8ac2-30b9c50be87f"
EXTRA_24_JULY_ID = "c44ec3cd-c0db-3aab-9b93-39794116a802"
JULY_23_ID = "03f68910-4b15-3189-b981-6379dc0e2249"


def _record(
    signed: str,
    file_id: str,
    *,
    diary: str,
    edition: str = "Normal",
    pending: bool = False,
):
    return {
        "ch_diario": diary,
        "dt_assinatura": signed,
        "nr_diario": 135,
        "nm_tipo_edicao": edition,
        "st_pendente": pending,
        "arquivos": [
            {
                "arquivo_diario": {
                    "id_file": file_id,
                    "filename": f"DODF-{diary}.pdf",
                },
                "ds_arquivo": "",
            }
        ],
    }


class JsonResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload):
        self._payload = payload
        self.url = "https://www.sinj.df.gov.br/sinj/ashx/Consulta/DiarioConsulta.ashx"
        self.text = json.dumps(payload)
        self.content = self.text.encode()

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class HtmlResponse:
    status_code = 200
    headers = {"Content-Type": "text/html"}
    url = "https://www.sinj.df.gov.br/sinj/PesquisarDiretorioDiario.aspx"
    text = "<html></html>"
    content = text.encode()

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, payload):
        self.headers = {"User-Agent": "test"}
        self.payload = payload
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        return JsonResponse(self.payload)


class FakeClient:
    request_timeout = (3, 10)

    def __init__(self, payload):
        self.session = FakeSession(payload)
        self.gets = []

    def get(self, url, **_kwargs):
        self.gets.append(url)
        return HtmlResponse()


def _collector(payload) -> ResilientDodfCollector:
    return ResilientDodfCollector(
        FakeClient(payload),
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
        "https://www.sinj.df.gov.br/sinj/Pesquisas.aspx",
    )


def test_directory_api_filters_exact_day_and_keeps_all_editions():
    normal = _record("24/07/2026", KNOWN_24_JULY_ID, diary="normal")
    extra = _record("24/07/2026", EXTRA_24_JULY_ID, diary="extra", edition="Extra")
    previous = _record("23/07/2026", JULY_23_ID, diary="previous")
    pending = _record(
        "24/07/2026",
        "621726bf-1848-3597-accb-1f945f466919",
        diary="pending",
        pending=True,
    )
    invalid = _record("24/07/2026", "not-a-file-id", diary="invalid")
    payload = {
        "hits": {
            "hits": [
                {"fields": {"partial": [normal]}},
                {"fields": {"partial": [json.dumps(extra)]}},
                {"fields": {"partial": [previous, pending, invalid]}},
            ]
        }
    }
    collector = _collector(payload)

    urls = collector._sinj_urls(date(2026, 7, 24))

    assert urls == [
        f"https://www.sinj.df.gov.br/sinj/BaixarArquivoDiario.aspx?id_file={KNOWN_24_JULY_ID}",
        f"https://www.sinj.df.gov.br/sinj/BaixarArquivoDiario.aspx?id_file={EXTRA_24_JULY_ID}",
    ]


def test_directory_api_uses_official_form_and_caches_month():
    payload = {
        "hits": {
            "hits": [
                {
                    "fields": {
                        "partial": [
                            _record("24/07/2026", KNOWN_24_JULY_ID, diary="24"),
                            _record("23/07/2026", JULY_23_ID, diary="23"),
                        ]
                    }
                }
            ]
        }
    }
    collector = _collector(payload)
    client = collector.client

    collector._sinj_urls(date(2026, 7, 24))
    collector._sinj_urls(date(2026, 7, 23))

    assert client.gets == [
        "https://www.sinj.df.gov.br/sinj/PesquisarDiretorioDiario.aspx"
    ]
    assert len(client.session.posts) == 1
    url, kwargs = client.session.posts[0]
    assert url == "https://www.sinj.df.gov.br/sinj/ashx/Consulta/DiarioConsulta.ashx"
    assert kwargs["params"] == {"iDisplayStart": "0", "iDisplayLength": "300"}
    assert kwargs["data"] == {
        "tipo_pesquisa": "diretorio_diario",
        "ch_tipo_fonte": "1",
        "ano": "2026",
        "mes": "7",
    }


def test_directory_payload_accepts_results_envelope_and_deduplicates_records():
    record = _record("24/07/2026", KNOWN_24_JULY_ID, diary="same")
    payload = {
        "results": [record, json.dumps(record)],
        "nested": {"copy": record},
    }

    records = ResilientDodfCollector._sinj_records_from_payload(payload)

    assert records == [record]


def test_directory_api_failure_uses_legacy_html_fallback(monkeypatch):
    collector = _collector({})

    def fail_post(*_args, **_kwargs):
        raise requests.ConnectTimeout("SINJ API indisponível")

    collector.client.session.post = fail_post
    monkeypatch.setattr(
        DodfCollector,
        "_sinj_urls",
        lambda _self, day: [f"legacy:{day.isoformat()}"],
    )

    assert collector._sinj_urls(date(2026, 7, 24)) == ["legacy:2026-07-24"]
