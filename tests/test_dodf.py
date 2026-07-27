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
