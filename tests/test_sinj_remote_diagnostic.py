from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sinj.df.gov.br/sinj/"
DIRECTORY = urljoin(BASE, "PesquisarDiretorioDiario.aspx")


def _json_or_text(response: requests.Response, limit: int = 12000):
    try:
        return response.json()
    except Exception:
        return " ".join(response.text.split())[:limit]


def _contexts(text: str, terms: tuple[str, ...], radius: int = 500, limit: int = 40):
    lowered = text.casefold()
    output: list[str] = []
    for term in terms:
        start = 0
        while len(output) < limit:
            index = lowered.find(term.casefold(), start)
            if index < 0:
                break
            snippet = " ".join(text[max(0, index-radius):index+radius].split())
            if snippet not in output:
                output.append(snippet)
            start = index + len(term)
    return output


def test_remote_sinj_directory_diagnostic():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "rss-diarios-diagnostic/2.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": DIRECTORY,
    })
    output: dict[str, object] = {}

    page = session.get(DIRECTORY, timeout=25)
    soup = BeautifulSoup(page.text, "html.parser")
    output["directory"] = {
        "status": page.status_code,
        "url": page.url,
        "selects": {
            select.get("id") or select.get("name") or "unknown": [
                {"value": option.get("value"), "text": " ".join(option.get_text(" ", strip=True).split())}
                for option in select.find_all("option")
            ]
            for select in soup.find_all("select")
        },
        "inline_contexts": _contexts(
            "\n".join(script.get_text("\n") for script in soup.find_all("script") if not script.get("src")),
            ("select_tipo_fonte", "select_ano", "select_mes", "diretorio", "ashx", "datatable", "form_pesquisa_diario"),
        ),
        "ashx_in_html": sorted(set(re.findall(r"(?:\.?\.?/)?ashx/[A-Za-z0-9_./-]+\.ashx", page.text, flags=re.I))),
    }

    relevant_scripts: dict[str, object] = {}
    for tag in soup.select("script[src]"):
        src = urljoin(page.url, str(tag.get("src", "")))
        try:
            response = session.get(src, timeout=25)
        except Exception as exc:
            relevant_scripts[src] = {"error": repr(exc)}
            continue
        contexts = _contexts(
            response.text,
            ("diretorio", "select_tipo_fonte", "select_ano", "select_mes", "DiarioDatatable", "ashx", "tipo_pesquisa"),
            radius=650,
            limit=80,
        )
        if contexts:
            relevant_scripts[src] = {
                "status": response.status_code,
                "length": len(response.text),
                "contexts": contexts,
                "ashx": sorted(set(re.findall(r"(?:\.?\.?/)?ashx/[A-Za-z0-9_./-]+\.ashx", response.text, flags=re.I))),
            }
    output["scripts"] = relevant_scripts

    probes = []
    common = {
        "tipo_pesquisa": "diretorio_diario",
        "ch_tipo_fonte": "1",
        "ano": "2026",
        "mes": "7",
        "draw": "1",
        "start": "0",
        "length": "200",
        "iDisplayStart": "0",
        "iDisplayLength": "200",
        "sEcho": "1",
    }
    candidates = [
        ("POST", DIRECTORY, common),
        ("GET", urljoin(BASE, "ResultadoDePesquisa"), common),
        ("GET", urljoin(BASE, "ResultadoDePesquisa.aspx"), common),
        ("POST", urljoin(BASE, "ashx/Datatable/DiarioDatatable.ashx"), common),
        ("GET", urljoin(BASE, "ashx/Datatable/DiarioDatatable.ashx"), common),
        ("POST", urljoin(BASE, "ashx/Consulta/DiarioDoDiaConsulta.ashx"), {"ch_tipo_fonte": "1"}),
    ]
    for method, url, payload in candidates:
        try:
            response = session.request(
                method,
                url,
                data=payload if method == "POST" else None,
                params=payload if method == "GET" else None,
                timeout=30,
            )
            body = _json_or_text(response)
            probes.append({
                "method": method,
                "url": response.url,
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "body": body,
                "id_files": sorted(set(re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27,}", response.text, flags=re.I)))[:50],
            })
        except Exception as exc:
            probes.append({"method": method, "url": url, "error": repr(exc)})
    output["probes"] = probes

    raise AssertionError("SINJ_DIRECTORY_DIAGNOSTIC\n" + json.dumps(output, ensure_ascii=False, indent=2)[:180000])
