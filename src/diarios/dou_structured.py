from __future__ import annotations

import json
import logging
from datetime import date, datetime, time
from html import unescape
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from diarios.dou import DouCollector, IN_HOSTS
from models import Document
from text_utils import clean_text

LOG = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")
SEARCH_SCRIPT_ID = "_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params"


class StructuredDouCollector(DouCollector):
    """Fallback público baseado no JSON consumido pelo próprio buscador do DOU.

    O formato é o mesmo adotado pelo Ro-DOU. Se o portal alterar esse JSON, o
    parser HTML herdado continua disponível como contingência.
    """

    @staticmethod
    def _public_records(html: str) -> list[dict[str, object]] | None:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.find("script", id=SEARCH_SCRIPT_ID)
        if script is None:
            return None
        raw = script.string or script.get_text()
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            LOG.warning("DOU público: JSON estruturado inválido")
            return None
        records = payload.get("jsonArray", []) if isinstance(payload, dict) else []
        return [record for record in records if isinstance(record, dict)]

    @staticmethod
    def _int_or_none(value: object) -> int | None:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    @classmethod
    def _document_from_record(cls, record: dict[str, object], day: date) -> Document | None:
        title = clean_text(str(record.get("title") or ""))
        slug = clean_text(str(record.get("urlTitle") or "")).lstrip("/")
        if not title or not slug or "/" in slug:
            return None
        url = urljoin("https://www.in.gov.br/web/dou/-/", slug)
        parsed = urlparse(url)
        if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in IN_HOSTS:
            return None

        raw_date = clean_text(str(record.get("pubDate") or ""))
        published_day = day
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                published_day = datetime.strptime(raw_date[:10], fmt).date()
                break
            except ValueError:
                continue
        if published_day != day:
            return None

        raw_content = unescape(str(record.get("content") or ""))
        text_value = clean_text(BeautifulSoup(raw_content, "html.parser").get_text(" ", strip=True))
        if not text_value:
            return None

        hierarchy = record.get("hierarchyStr") or record.get("hierarchyList") or ""
        if isinstance(hierarchy, list):
            hierarchy = " / ".join(clean_text(str(part)) for part in hierarchy if clean_text(str(part)))
        return Document(
            source="dou",
            source_label="Diário Oficial da União",
            title=title,
            url=url,
            published_at=datetime.combine(day, time(hour=6), tzinfo=BRT),
            text=text_value,
            edition=clean_text(str(record.get("editionNumber") or record.get("edition") or "")),
            section=clean_text(str(record.get("pubName") or "")),
            page=cls._int_or_none(record.get("numberPage") or record.get("page")),
            publication_type=clean_text(str(record.get("artType") or "")),
            organization=clean_text(str(hierarchy)),
        )

    def _collect_public(self, day: date) -> list[Document]:
        br_date = day.strftime("%d-%m-%Y")
        documents: list[Document] = []
        seen_urls: set[str] = set()
        fallback_urls: list[str] = []
        succeeded = False
        last_error: Exception | None = None

        for term in self.public_search_terms:
            try:
                response = self.client.get(
                    self.public_search_url,
                    params={
                        "q": term,
                        "s": "todos",
                        "exactDate": "personalizado",
                        "sortType": "0",
                        "publishFrom": br_date,
                        "publishTo": br_date,
                    },
                )
                succeeded = True
            except Exception as exc:
                last_error = exc
                LOG.warning("DOU público: busca por %r falhou: %s", term, exc)
                continue

            records = self._public_records(response.text)
            if records is not None:
                for record in records:
                    document = self._document_from_record(record, day)
                    if document and document.url not in seen_urls:
                        seen_urls.add(document.url)
                        documents.append(document)
                continue

            for url in self._public_result_links(response.text, response.url):
                if url not in seen_urls and url not in fallback_urls:
                    fallback_urls.append(url)

        if not succeeded and last_error is not None:
            raise last_error

        # Contingência: se o JSON desaparecer, abre as páginas como no coletor anterior.
        for url in fallback_urls:
            try:
                response = self.client.get(url)
                document = self._document_from_public_html(response.text, response.url, day)
            except Exception as exc:
                LOG.warning("DOU público: falha ao abrir %s: %s", url, exc)
                continue
            if document and document.url not in seen_urls:
                seen_urls.add(document.url)
                documents.append(document)
        return documents
