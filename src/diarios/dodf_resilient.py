from __future__ import annotations

import io
import json
import logging
import re
from datetime import date, datetime, time
from typing import Any
from urllib.parse import urljoin, urlparse

import fitz
import requests
from bs4 import BeautifulSoup

from diarios.dodf import BRT, DodfCollector, OFFICIAL_HOSTS, SINJ_HOSTS
from models import Document
from text_utils import clean_text

LOG = logging.getLogger(__name__)
SINJ_DODF_SOURCE_KEY = "1"
SINJ_FILE_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    flags=re.I,
)


class PrimaryCircuitOpen(ConnectionError):
    pass


class PrimaryPdfFailure(ConnectionError):
    pass


class ResilientDodfCollector(DodfCollector):
    """DODF com portal primário curto e fallback oficial pelo diretório do SINJ."""

    def __init__(
        self,
        *args,
        primary_connect_timeout: int = 3,
        primary_read_timeout: int = 10,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.primary_connect_timeout = primary_connect_timeout
        self.primary_read_timeout = primary_read_timeout
        self.primary_circuit_open = False
        self.primary_circuit_reason = ""
        self.primary_attempts = 0
        self.primary_skipped_dates: list[str] = []
        self._sinj_month_cache: dict[tuple[int, int], list[dict[str, Any]]] = {}

    def _open_circuit(self, reason: Exception | str) -> None:
        self.primary_circuit_open = True
        self.primary_circuit_reason = str(reason)[:500]

    def list_pdf_urls(self, day: date) -> list[str]:
        if self.primary_circuit_open:
            raise PrimaryCircuitOpen(self.primary_circuit_reason or "circuito primário aberto")

        last_error: Exception | None = None
        had_successful_response = False
        for daily_url in self._daily_candidates():
            self.primary_attempts += 1
            try:
                response = requests.get(
                    daily_url,
                    params={"data": self._timestamp_for(day)},
                    headers=dict(self.client.session.headers),
                    timeout=(self.primary_connect_timeout, self.primary_read_timeout),
                    allow_redirects=True,
                )
                response.raise_for_status()
                had_successful_response = True
            except (requests.ConnectTimeout, requests.ConnectionError) as exc:
                last_error = exc
                LOG.warning(
                    "DODF %s: conexão primária indisponível em %s; circuito será aberto: %s",
                    day.isoformat(),
                    daily_url,
                    exc,
                )
                break
            except requests.RequestException as exc:
                last_error = exc
                LOG.warning("DODF %s: endpoint %s indisponível: %s", day.isoformat(), daily_url, exc)
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            urls: list[str] = []
            for anchor in soup.select("a[href]"):
                href = str(anchor.get("href", ""))
                if "visualizar-pdf" not in href.casefold():
                    continue
                absolute = urljoin(response.url, href)
                parsed = urlparse(absolute)
                if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in OFFICIAL_HOSTS:
                    LOG.warning("DODF: link de PDF externo/inseguro ignorado: %s", absolute)
                    continue
                if absolute not in urls:
                    urls.append(absolute)
            if urls:
                return urls
            LOG.info("DODF %s: endpoint primário respondeu sem PDFs", day.isoformat())

        # Uma resposta HTTP válida, ainda que sem PDFs, torna obsoleto qualquer
        # erro de candidato anterior. Não abrimos circuito com erro stale.
        if had_successful_response:
            return []
        if last_error is not None:
            raise last_error
        return []

    @staticmethod
    def _sinj_records_from_payload(payload: Any) -> list[dict[str, Any]]:
        """Localiza registros de diário mesmo se o SINJ mudar o envelope JSON."""
        records: list[dict[str, Any]] = []
        seen: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, str):
                stripped = value.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        visit(json.loads(stripped))
                    except (TypeError, ValueError, json.JSONDecodeError):
                        return
                return
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, dict):
                return

            if "dt_assinatura" in value and "arquivos" in value:
                identity = str(
                    value.get("ch_diario")
                    or value.get("ch_para_nao_duplicacao")
                    or (
                        value.get("dt_assinatura"),
                        value.get("nr_diario"),
                        value.get("nm_tipo_edicao"),
                        value.get("secao_diario"),
                    )
                )
                if identity not in seen:
                    seen.add(identity)
                    records.append(value)
                return

            for child in value.values():
                visit(child)

        visit(payload)
        return records

    def _sinj_month_records(self, day: date) -> list[dict[str, Any]]:
        cache_key = (day.year, day.month)
        cached = self._sinj_month_cache.get(cache_key)
        if cached is not None:
            return cached

        directory_url = urljoin(self.sinj_search_url, "PesquisarDiretorioDiario.aspx")
        api_url = urljoin(self.sinj_search_url, "ashx/Consulta/DiarioConsulta.ashx")

        # Replica a navegação oficial antes do AJAX e mantém cookies na mesma sessão.
        self.client.get(directory_url)
        response = self.client.session.post(
            api_url,
            params={"iDisplayStart": "0", "iDisplayLength": "300"},
            data={
                "tipo_pesquisa": "diretorio_diario",
                "ch_tipo_fonte": SINJ_DODF_SOURCE_KEY,
                "ano": str(day.year),
                "mes": str(day.month),
            },
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": directory_url,
            },
            timeout=self.client.request_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        records = self._sinj_records_from_payload(payload)
        self._sinj_month_cache[cache_key] = records
        LOG.info(
            "SINJ: diretório oficial retornou %d registros para %02d/%d",
            len(records),
            day.month,
            day.year,
        )
        return records

    @staticmethod
    def _sinj_file_ids(record: dict[str, Any]) -> list[str]:
        output: list[str] = []
        arquivos = record.get("arquivos")
        if not isinstance(arquivos, list):
            return output
        for entry in arquivos:
            if not isinstance(entry, dict):
                continue
            arquivo = entry.get("arquivo_diario")
            if not isinstance(arquivo, dict):
                continue
            file_id = str(arquivo.get("id_file") or "").strip()
            if SINJ_FILE_ID_RE.fullmatch(file_id) and file_id not in output:
                output.append(file_id)
        return output

    def _sinj_urls(self, day: date) -> list[str]:
        """Descobre os arquivos pela API oficial do diretório, filtrando a data exata."""
        try:
            records = self._sinj_month_records(day)
        except Exception as exc:
            LOG.warning("SINJ: API de diretórios falhou; usando pesquisa HTML legada: %s", exc)
            return super()._sinj_urls(day)

        target = day.strftime("%d/%m/%Y")
        urls: list[str] = []
        for record in records:
            if clean_text(str(record.get("dt_assinatura") or "")) != target:
                continue
            if record.get("st_pendente") is True:
                continue
            for file_id in self._sinj_file_ids(record):
                absolute = urljoin(
                    self.sinj_search_url,
                    f"BaixarArquivoDiario.aspx?id_file={file_id}",
                )
                parsed = urlparse(absolute)
                if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in SINJ_HOSTS:
                    continue
                if absolute not in urls:
                    urls.append(absolute)

        LOG.info("SINJ %s: API de diretórios encontrou %d arquivo(s)", day.isoformat(), len(urls))
        return urls

    def _collect_primary(self, day: date) -> list[Document]:
        """Baixa todos os PDFs e só propaga falha quando cada arquivo falhou."""
        pdf_urls = self.list_pdf_urls(day)
        documents: list[Document] = []
        failures: list[Exception] = []

        for pdf_url in pdf_urls:
            edition = self._edition_from_url(pdf_url)
            per_pdf_documents: list[Document] = []
            try:
                response = self.client.get(pdf_url)
                pdf = fitz.open(stream=io.BytesIO(response.content), filetype="pdf")
                try:
                    for page_number, page in enumerate(pdf, start=1):
                        text_value = clean_text(page.get_text("text"))
                        if not text_value:
                            continue
                        per_pdf_documents.append(
                            Document(
                                source="dodf",
                                source_label="Diário Oficial do Distrito Federal",
                                title=f"{edition} — página {page_number}",
                                url=f"{pdf_url}#page={page_number}",
                                published_at=datetime.combine(day, time(hour=6), tzinfo=BRT),
                                text=text_value,
                                edition=edition,
                                page=page_number,
                            )
                        )
                finally:
                    pdf.close()
            except Exception as exc:
                failures.append(exc)
                LOG.exception("Falha ao baixar, abrir ou processar PDF do DODF: %s", pdf_url)
                continue

            # Só incorpora as páginas depois que leitura e fechamento terminam.
            # Um PDF parcialmente processado e depois corrompido é tratado como falha.
            documents.extend(per_pdf_documents)

        if pdf_urls and len(failures) == len(pdf_urls):
            raise PrimaryPdfFailure(
                f"todos os {len(pdf_urls)} PDFs primários falharam; "
                f"primeiro erro: {failures[0]}"
            )
        return documents

    def _collect_fallback(self, day: date, reason: Exception | str) -> list[Document]:
        self.fallback_reason = str(reason)[:500]
        LOG.warning("DODF %s: acionando fallback SINJ: %s", day.isoformat(), reason)
        try:
            documents = self._collect_sinj(day)
        except Exception as fallback_error:
            raise RuntimeError(
                f"DODF e SINJ indisponíveis: primário={reason}; fallback={fallback_error}"
            ) from fallback_error
        self.backend = "sinj"
        LOG.info("DODF %s: fallback SINJ retornou %d documentos", day.isoformat(), len(documents))
        return documents

    def collect(self, day: date) -> list[Document]:
        if day.weekday() >= 5:
            self.primary_skipped_dates.append(day.isoformat())
            return self._collect_fallback(day, "fim de semana: portal diário primário não consultado")

        if self.primary_circuit_open:
            self.primary_skipped_dates.append(day.isoformat())
            return self._collect_fallback(
                day,
                f"circuito primário aberto: {self.primary_circuit_reason}",
            )

        try:
            documents = self._collect_primary(day)
            if documents:
                self.backend = "dodf"
                return documents
            primary_error: Exception = RuntimeError("endpoint primário sem documentos")
        except (requests.RequestException, ConnectionError) as exc:
            self._open_circuit(exc)
            primary_error = exc
        except Exception as exc:
            self._open_circuit(exc)
            primary_error = exc

        return self._collect_fallback(day, primary_error)
