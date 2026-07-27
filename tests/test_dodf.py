from datetime import date

from diarios.dodf import DodfCollector


class Response:
    url = "https://www.dodf.df.gov.br/dodf/jornal/diario?data=1"
    text = '''
    <a href="/dodf/jornal/visualizar-pdf?arquivo=DODF+1.pdf">PDF</a>
    <a href="https://evil.example/visualizar-pdf?arquivo=x.pdf">Externo</a>
    '''


class Client:
    def get(self, *_args, **_kwargs):
        return Response()


def test_lists_only_official_pdf_links():
    collector = DodfCollector(Client(), "https://www.dodf.df.gov.br/dodf/jornal/diario")
    urls = collector.list_pdf_urls(date(2026, 7, 27))
    assert urls == ["https://www.dodf.df.gov.br/dodf/jornal/visualizar-pdf?arquivo=DODF+1.pdf"]


def test_tries_non_www_host_first():
    collector = DodfCollector(Client(), "https://www.dodf.df.gov.br/dodf/jornal/diario")
    assert collector._daily_candidates()[0].startswith("https://dodf.df.gov.br/")


def test_parse_sinj_result_links():
    html = '''
    <a href="/sinj/TextoArquivoDiario.aspx?id_file=53964389-f756-33d0-91d0-fae8298a04e3">DODF</a>
    <a href="https://evil.example/sinj/TextoArquivoDiario.aspx?id_file=abc">Externo</a>
    '''
    urls = DodfCollector._sinj_result_links(
        html,
        "https://www.sinj.df.gov.br/sinj/Pesquisas.aspx",
    )
    assert urls == [
        "https://www.sinj.df.gov.br/sinj/TextoArquivoDiario.aspx?id_file=53964389-f756-33d0-91d0-fae8298a04e3"
    ]


def test_split_sinj_pages():
    text = (
        "Capa e conteúdo da página um. "
        "PÁGINA 2 Diário Oficial do Distrito Federal Nº 133 conteúdo dois. "
        "PÁGINA 3 Diário Oficial do Distrito Federal Nº 133 conteúdo três."
    )
    pages = DodfCollector._split_sinj_pages(text)
    assert [page for page, _ in pages] == [1, 2, 3]
    assert "conteúdo dois" in pages[1][1]


def test_uses_sinj_when_primary_fails():
    collector = DodfCollector(Client(), "https://dodf.df.gov.br/dodf/jornal/diario")
    collector._collect_primary = lambda _day: (_ for _ in ()).throw(ConnectionError("timeout"))
    collector._collect_sinj = lambda _day: []
    assert collector.collect(date(2026, 7, 27)) == []
    assert collector.backend == "sinj"
    assert "timeout" in collector.fallback_reason
