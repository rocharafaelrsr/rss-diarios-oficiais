from datetime import date

from diarios.dodf_resilient import ResilientDodfCollector
from http_client import HttpClient

KNOWN_ID = "d00d5df2-c3f3-3101-8ac2-30b9c50be87f"
KNOWN_URL = f"https://www.sinj.df.gov.br/sinj/BaixarArquivoDiario.aspx?id_file={KNOWN_ID}"


def test_live_sinj_directory_finds_and_parses_known_dodf():
    client = HttpClient(timeout=35, user_agent="rss-diarios-live-verification/1.0")
    collector = ResilientDodfCollector(
        client,
        "https://www.dodf.df.gov.br/dodf/jornal/diario",
        "https://www.sinj.df.gov.br/sinj/Pesquisas.aspx",
    )

    urls = collector._sinj_urls(date(2026, 7, 24))
    assert KNOWN_URL in urls

    response = client.get(KNOWN_URL)
    assert response.content[:4] == b"%PDF"
    documents = collector._documents_from_pdf(response.content, response.url, date(2026, 7, 24))
    assert documents
    assert documents[0].published_at.date() == date(2026, 7, 24)
