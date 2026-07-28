from __future__ import annotations

import logging
from datetime import date
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from diarios.dodf import DodfCollector, OFFICIAL_HOSTS
from models import Document

LOG = logging.getLogger(__name__)


class PrimaryCircuitOpen(ConnectionError):
    pass


class ResilientDodfCollector(DodfCollector):
    """DODF com tentativa primária curta e circuito aberto por execução.

    O portal `dodf.df.gov.br` frequentemente não aceita conexões dos runners do
    GitHub. Depois da primeira falha de conexão, repetir os mesmos timeouts para
    cada data não acrescenta cobertura: as datas seguintes seguem diretamente
    para o SINJ. Fins de semana também consultam somente o SINJ, preservando a
    possibilidade de edição extraordinária sem testar um endpoint diário vazio.
    """

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

    def _open_circuit(self, reason: Exception | str) -> None:
        self.primary_circuit_open = True
        self.primary_circuit_reason = str(reason)[:500]

    def list_pdf_urls(self, day: date) -> list[str]:
        if self.primary_circuit_open:
            raise PrimaryCircuitOpen(self.primary_circuit_reason or "circuito primário aberto")

        last_error: Exception | None = None
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

        if last_error is not None:
            raise last_error
        return []

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
