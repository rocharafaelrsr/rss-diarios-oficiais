from __future__ import annotations

import json
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://www.sinj.df.gov.br/sinj/"
PAGES = [
    "Pesquisas.aspx",
    "ResultadoDePesquisa.aspx?all=DoDF&tipo_pesquisa=geral",
    "PesquisarDiretorioDiario.aspx",
    "PesquisarTextoDiario.aspx",
]
KEYWORDS = (
    "diario",
    "diretorio",
    "id_file",
    "textoarquivodiario",
    "baixararquivodiario",
    "resultadodepesquisa",
    "pesquisardiretorio",
    "pesquisartexto",
)


def _compact(value: str, limit: int = 220) -> str:
    return " ".join(value.split())[:limit]


def test_remote_sinj_diagnostic():
    session = requests.Session()
    session.headers["User-Agent"] = "rss-diarios-diagnostic/1.0"
    output: dict[str, object] = {"pages": {}, "scripts": {}}
    script_urls: list[str] = []

    for relative in PAGES:
        url = urljoin(BASE, relative)
        response = session.get(url, timeout=25)
        soup = BeautifulSoup(response.text, "html.parser")
        page: dict[str, object] = {
            "status": response.status_code,
            "url": response.url,
            "length": len(response.text),
            "title": _compact(soup.title.get_text(" ", strip=True) if soup.title else ""),
            "forms": [],
            "links": [],
        }
        for form in soup.find_all("form"):
            controls = []
            for control in form.find_all(["input", "select", "textarea", "button"]):
                controls.append(
                    {
                        "tag": control.name,
                        "type": control.get("type"),
                        "name": control.get("name"),
                        "id": control.get("id"),
                        "value": _compact(str(control.get("value", "")), 160),
                    }
                )
            page["forms"].append(
                {
                    "id": form.get("id"),
                    "method": form.get("method"),
                    "action": form.get("action"),
                    "controls": controls,
                }
            )
        for anchor in soup.select("a[href]"):
            href = urljoin(response.url, str(anchor.get("href", "")))
            text = _compact(anchor.get_text(" ", strip=True))
            if any(key in href.casefold() or key in text.casefold() for key in KEYWORDS):
                page["links"].append({"href": href, "text": text})
        for script in soup.select("script[src]"):
            src = urljoin(response.url, str(script.get("src", "")))
            if urlparse(src).hostname in {"sinj.df.gov.br", "www.sinj.df.gov.br"} and src not in script_urls:
                script_urls.append(src)
        output["pages"][relative] = page

    for src in script_urls:
        try:
            response = session.get(src, timeout=25)
        except Exception as exc:  # pragma: no cover - diagnostic only
            output["scripts"][src] = {"error": repr(exc)}
            continue
        lowered = response.text.casefold()
        hits = []
        for keyword in KEYWORDS:
            start = 0
            while True:
                index = lowered.find(keyword, start)
                if index < 0:
                    break
                hits.append(_compact(response.text[max(0, index - 240): index + 700], 940))
                start = index + len(keyword)
                if len(hits) >= 30:
                    break
            if len(hits) >= 30:
                break
        if hits:
            output["scripts"][src] = {
                "status": response.status_code,
                "length": len(response.text),
                "hits": hits,
            }

    raise AssertionError("SINJ_REMOTE_DIAGNOSTIC\n" + json.dumps(output, ensure_ascii=False, indent=2)[:120000])
