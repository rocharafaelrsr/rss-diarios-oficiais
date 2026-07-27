from __future__ import annotations

import io
import logging
from datetime import date, datetime, time
from urllib.parse import parse_qs, unquote_plus, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

import fitz
from bs4 import BeautifulSoup

from http_client import HttpClient
from models import Document
from text_utils import clean_text

LOG = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")
OFFICIAL_HOSTS = {"dodf.df.gov.br", "www.dodf.df.gov.br"}


class DodfCollector:
    def __init__(self, client: HttpClient, daily_url: str) -> None:
        self.client = client
        self.daily_url = daily_url
        self._primed_hosts: set[str] = set()

    @staticmethod
    def _timestamp_for(day: date) -> int:
        return int(datetime.combine(day, time.min, tzinfo=BRT).timestamp())

    @staticmethod
    def _edition_from_url(url: str) -> str:
        query = parse_qs(urlparse(url).query)
        filename = unquote_plus((query.get("arquivo") or [""])[0])
        if filename:
            return filename.removesuffix(".pdf").strip()
        return "DODF"

    def _daily_candidates(self) -> list[str]:
        parsed = urlparse(self.daily_url)
        host = (parsed.hostname or "").casefold()
        hosts = [host]
        if host.startswith("www."):
            hosts.insert(0, host.removeprefix("www."))
        elif host:
            hosts.append(f"www.{host}")
        output: list[str] = []
        for candidate_host in hosts:
            netloc = candidate_host
            if parsed.port:
                netloc = f"{candidate_host}:{parsed.port}"
            candidate = urlunparse(parsed._replace(netloc=netloc))
            if candidate not in output:
                output.append(candidate)
        return output

    def _prime(self, daily_url: str) -> None:
        parsed = urlparse(daily_url)
        host = (parsed.hostname or "").casefold()
        if not host or host in self._primed_hosts:
            return
        self._primed_hosts.add(host)
        root = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        try:
            # Alguns WAFs só liberam a rota interna depois de criarem cookies na
            # página inicial. A falha do aquecimento não impede a tentativa direta.
            self.client.get(root)
        except Exception as exc:
            LOG.info("DODF: aquecimento de sessão falhou em %s: %s", host, exc)

    def list_pdf_urls(self, day: date) -> list[str]:
        last_error: Exception | None = None
        for daily_url in self._daily_candidates():
            self._prime(daily_url)
            try:
                response = self.client.get(daily_url, params={"data": self._timestamp_for(day)})
            except Exception as exc:
                last_error = exc
                LOG.warning("DODF %s: endpoint %s indisponível: %s", day.isoformat(), daily_url, exc)
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            urls: list[str] = []
            for anchor in soup.select("a[href]"):
                href = anchor.get("href", "")
                if "visualizar-pdf" not in href.lower():
                    continue
                absolute = urljoin(response.url, href)
                parsed = urlparse(absolute)
                if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in OFFICIAL_HOSTS:
                    LOG.warning("DODF: link de PDF externo/inseguro ignorado: %s", absolute)
                    continue
                if absolute not in urls:
                    urls.append(absolute)
            if not urls:
                LOG.warning("DODF %s: página diária sem links de PDF", day.isoformat())
            return urls

        if last_error is not None:
            raise last_error
        return []

    def collect(self, day: date) -> list[Document]:
        documents: list[Document] = []
        for pdf_url in self.list_pdf_urls(day):
            edition = self._edition_from_url(pdf_url)
            try:
                response = self.client.get(pdf_url)
                pdf = fitz.open(stream=io.BytesIO(response.content), filetype="pdf")
            except Exception:
                LOG.exception("Falha ao baixar/abrir PDF do DODF: %s", pdf_url)
                continue
            try:
                for page_number, page in enumerate(pdf, start=1):
                    text_value = clean_text(page.get_text("text"))
                    if not text_value:
                        continue
                    documents.append(
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
        return documents
