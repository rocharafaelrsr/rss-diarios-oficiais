from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sinj.df.gov.br/sinj/"
DIRECTORY = urljoin(BASE, "PesquisarDiretorioDiario.aspx")
API = urljoin(BASE, "ashx/Consulta/DiarioConsulta.ashx")


def _extract_js_json(text: str, variable: str):
    match = re.search(rf"var\s+{re.escape(variable)}\s*=\s*(\{{.*?\}});", text, flags=re.S)
    if not match:
        return None
    return json.loads(match.group(1))


def _summarize(value, depth: int = 0):
    if depth > 5:
        return "<depth>"
    if isinstance(value, dict):
        return {str(k): _summarize(v, depth + 1) for k, v in list(value.items())[:80]}
    if isinstance(value, list):
        return [_summarize(v, depth + 1) for v in value[:40]]
    if isinstance(value, str):
        return value[:1000]
    return value


def test_remote_sinj_directory_api_diagnostic():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "rss-diarios-diagnostic/3.0",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": DIRECTORY,
    })

    page = session.get(DIRECTORY, timeout=25)
    soup = BeautifulSoup(page.text, "html.parser")
    inline = "\n".join(script.get_text("\n") for script in soup.find_all("script") if not script.get("src"))
    sources = _extract_js_json(inline, "tiposDeFonte")
    years = _extract_js_json(inline, "anosDeAssinatura")

    source_rows = (sources or {}).get("results", [])
    dodf = next(
        (row for row in source_rows if str(row.get("nm_tipo_fonte", "")).strip().casefold() == "dodf"),
        None,
    )
    source_key = str((dodf or {}).get("ch_tipo_fonte", ""))

    payload = {
        "tipo_pesquisa": "diretorio_diario",
        "ch_tipo_fonte": source_key,
        "ano": "2026",
        "mes": "7",
    }
    response = session.post(
        API,
        params={"iDisplayStart": "0", "iDisplayLength": "300"},
        data=payload,
        timeout=30,
    )
    try:
        api_body = response.json()
    except Exception:
        api_body = {"raw": " ".join(response.text.split())[:30000]}

    # Compara com a chave curta usada pelo botão "Diário do Dia".
    today_response = session.post(
        urljoin(BASE, "ashx/Consulta/DiarioDoDiaConsulta.ashx"),
        data={"ch_tipo_fonte": "1"},
        timeout=30,
    )
    try:
        today_body = today_response.json()
    except Exception:
        today_body = {"raw": " ".join(today_response.text.split())[:20000]}

    output = {
        "directory_status": page.status_code,
        "source_count": len(source_rows),
        "dodf_source": dodf,
        "years": years,
        "api_request": {"url": response.url, "payload": payload},
        "api_status": response.status_code,
        "api_content_type": response.headers.get("Content-Type"),
        "api_body": _summarize(api_body),
        "api_id_files": sorted(set(re.findall(r"[0-9a-f]{8}-[0-9a-f-]{27,}", response.text, flags=re.I)))[:100],
        "today_status": today_response.status_code,
        "today_body": _summarize(today_body),
    }
    raise AssertionError("SINJ_API_DIAGNOSTIC\n" + json.dumps(output, ensure_ascii=False, indent=2)[:180000])
