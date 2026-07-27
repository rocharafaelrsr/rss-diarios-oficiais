from __future__ import annotations

import io
import logging
import re
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
SINJ_HOSTS = {"sinj.df.gov.br", "www.sinj.df.gov.br"}


class DodfCollector:
    def __init__(
        self,
        client: HttpClient,
        daily_url: str,
        sinj_search_url: str = "https://www.sinj.df.gov.br/sinj/Pesquisas.aspx",
    ) -> None:
        self.client = client
        self.daily_url = daily_url
        self.sinj_search_url = sinj_search_url
        self._primed_hosts: set[str] = set()
        self.backend = "dodf"
        self.fallback_reason = ""

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

    def _prime(self, url: str) -> None:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold()
        if not host or host in self._primed_hosts:
            return
        self._primed_hosts.add(host)
        root = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        try:
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
                href = str(anchor.get("href", ""))
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

    @staticmethod
    def _sinj_result_links(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        candidates = [str(a.get("href", "")) for a in soup.select("a[href]")]
        candidates.extend(
            match.group(0).replace("&amp;", "&")
            for match in re.finditer(
                r"(?:https?://(?:www\.)?sinj\.df\.gov\.br)?/sinj/(?:Texto|Baixar)ArquivoDiario\.aspx\?id_file=[0-9a-f-]{16,}",
                html,
                flags=re.I,
            )
        )
        for href in candidates:
            lowered = href.casefold()
            if "textoarquivodiario" not in lowered and "baixararquivodiario" not in lowered:
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in SINJ_HOSTS:
                continue
            if absolute not in urls:
                urls.append(absolute)
        return urls

    def _sinj_urls(self, day: date) -> list[str]:
        br_date = day.strftime("%d/%m/%Y")
        endpoints = [
            self.sinj_search_url,
            urljoin(self.sinj_search_url, "Pesquisas.aspx"),
        ]
        queries = [
            f'DODF "{br_date}"',
            f'"Diário Oficial do Distrito Federal" "{br_date}"',
        ]
        last_error: Exception | None = None
        urls: list[str] = []
        for endpoint in dict.fromkeys(endpoints):
            self._prime(endpoint)
            for query in queries:
                try:
                    response = self.client.get(
                        endpoint,
                        params={"all": query, "tipo_pesquisa": "geral"},
                    )
                except Exception as exc:
                    last_error = exc
                    LOG.warning("SINJ: pesquisa falhou em %s: %s", endpoint, exc)
                    continue
                for url in self._sinj_result_links(response.text, response.url):
                    if url not in urls:
                        urls.append(url)
            if urls:
                break
        if not urls and last_error is not None:
            raise last_error
        return urls

    @staticmethod
    def _sinj_edition(text: str, title: str) -> str:
        value = f"{title}\n{text[:1200]}"
        match = re.search(
            r"Diário Oficial do Distrito Federal(?:\s*-\s*Edição\s+([^,\n]+))?\s+N[º°]?\s*([0-9]+(?:-[A-Z])?)",
            value,
            flags=re.I,
        )
        if match:
            edition_type = clean_text(match.group(1) or "")
            number = match.group(2)
            return f"DODF {number}" + (f" — {edition_type}" if edition_type else "")
        match = re.search(r"DODF\s+N[º°]?\s*([0-9]+(?:-[A-Z])?)", value, flags=re.I)
        return f"DODF {match.group(1)}" if match else "DODF (SINJ)"

    @staticmethod
    def _split_sinj_pages(text: str) -> list[tuple[int, str]]:
        cleaned = clean_text(text)
        marker = re.compile(
            r"(?=\bPÁGINA\s+(\d+)\s+Diário Oficial do Distrito Federal)",
            flags=re.I,
        )
        matches = list(marker.finditer(cleaned))
        if not matches:
            return [(1, cleaned)] if cleaned else []
        output: list[tuple[int, str]] = []
        first = cleaned[: matches[0].start()].strip()
        if first:
            output.append((1, first))
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(cleaned)
            page = int(match.group(1))
            chunk = cleaned[match.start():end].strip()
            if chunk:
                output.append((page, chunk))
        return output

    @staticmethod
    def _matches_day(text: str, day: date) -> bool:
        month_names = (
            "JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
            "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO",
        )
        upper = text.upper()
        numeric = day.strftime("%d/%m/%Y")
        long_value = f"{day.day:02d} DE {month_names[day.month - 1]} DE {day.year}"
        long_no_zero = f"{day.day} DE {month_names[day.month - 1]} DE {day.year}"
        return numeric in text or long_value in upper or long_no_zero in upper

    def _documents_from_pdf(self, payload: bytes, url: str, day: date) -> list[Document]:
        documents: list[Document] = []
        pdf = fitz.open(stream=io.BytesIO(payload), filetype="pdf")
        try:
            first_text = clean_text(pdf[0].get_text("text")) if len(pdf) else ""
            if first_text and not self._matches_day(first_text, day):
                return []
            edition = self._sinj_edition(first_text, "")
            for page_number, page in enumerate(pdf, start=1):
                text_value = clean_text(page.get_text("text"))
                if not text_value:
                    continue
                documents.append(
                    Document(
                        source="dodf",
                        source_label="Diário Oficial do Distrito Federal",
                        title=f"{edition} — página {page_number}",
                        url=f"{url}#page={page_number}",
                        published_at=datetime.combine(day, time(hour=6), tzinfo=BRT),
                        text=text_value,
                        edition=edition,
                        page=page_number,
                    )
                )
        finally:
            pdf.close()
        return documents

    def _collect_sinj(self, day: date) -> list[Document]:
        documents: list[Document] = []
        for url in self._sinj_urls(day):
            response = self.client.get(url)
            content_type = response.headers.get("Content-Type", "").casefold() if hasattr(response, "headers") else ""
            if "pdf" in content_type or response.content[:4] == b"%PDF":
                documents.extend(self._documents_from_pdf(response.content, response.url, day))
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            title = clean_text((soup.title.get_text(" ", strip=True) if soup.title else ""))
            text_value = clean_text(soup.get_text(" ", strip=True))
            if not self._matches_day(text_value, day):
                continue
            edition = self._sinj_edition(text_value, title)
            for page_number, page_text in self._split_sinj_pages(text_value):
                if not page_text:
                    continue
                documents.append(
                    Document(
                        source="dodf",
                        source_label="Diário Oficial do Distrito Federal",
                        title=f"{edition} — página {page_number}",
                        url=f"{response.url}#page={page_number}",
                        published_at=datetime.combine(day, time(hour=6), tzinfo=BRT),
                        text=page_text,
                        edition=edition,
                        page=page_number,
                    )
                )
        return documents

    def _collect_primary(self, day: date) -> list[Document]:
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

    def collect(self, day: date) -> list[Document]:
        try:
            documents = self._collect_primary(day)
            if documents:
                self.backend = "dodf"
                return documents
            primary_error: Exception = RuntimeError("endpoint primário sem documentos")
        except Exception as exc:
            primary_error = exc
        self.fallback_reason = str(primary_error)[:500]
        LOG.warning("DODF %s: acionando fallback SINJ: %s", day.isoformat(), primary_error)
        try:
            documents = self._collect_sinj(day)
        except Exception as fallback_error:
            raise RuntimeError(
                f"DODF e SINJ indisponíveis: primário={primary_error}; fallback={fallback_error}"
            ) from fallback_error
        self.backend = "sinj"
        LOG.info("DODF %s: fallback SINJ retornou %d documentos", day.isoformat(), len(documents))
        return documents
