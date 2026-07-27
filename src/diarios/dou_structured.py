from __future__ import annotations

import json
import logging
import re
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
    """Fallback público baseado no JSON consumido pelo próprio buscador do DOU."""

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
        if not isinstance(payload, dict) or "jsonArray" not in payload:
            return None
        records = payload["jsonArray"]
        if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
            LOG.warning("DOU público: jsonArray com formato inesperado")
            return None
        return records

    @staticmethod
    def _page_count(html: str) -> int:
        soup = BeautifulSoup(html, "html.parser")
        last = soup.find("button", id="lastPage")
        if last is not None:
            try:
                return max(1, min(50, int(clean_text(last.get_text()))))
            except ValueError:
                pass
        return 2 if soup.find("button", id="2btn") is not None else 1

    @staticmethod
    def _html_pagination_urls(html: str, base_url: str) -> list[str]:
        """Extrai URLs de paginação expostas em links, atributos ou onclick."""
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[str] = []
        for node in soup.select("[href], [data-href], [data-url], [onclick]"):
            for attribute in ("href", "data-href", "data-url"):
                value = str(node.get(attribute, "")).strip()
                if value:
                    candidates.append(value)
            onclick = str(node.get("onclick", ""))
            candidates.extend(
                match.group(1)
                for match in re.finditer(
                    r"['\"]([^'\"]*(?:newPage|currentPage)=[^'\"]+)['\"]",
                    onclick,
                    flags=re.I,
                )
            )

        urls: list[str] = []
        for candidate in candidates:
            if "newpage" not in candidate.casefold() and "currentpage" not in candidate.casefold():
                continue
            # BeautifulSoup já decodifica entidades HTML nos atributos. Aplicar
            # html.unescape novamente corromperia `&currentPage` como `&curren`.
            absolute = urljoin(base_url, candidate)
            parsed = urlparse(absolute)
            if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in IN_HOSTS:
                continue
            if "/consulta/-/buscar/dou" not in parsed.path:
                continue
            if absolute not in urls:
                urls.append(absolute)
        return urls

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

    def _add_html_result_links(
        self,
        response,
        *,
        seen_urls: set[str],
        fallback_urls: list[str],
    ) -> None:
        for url in self._public_result_links(response.text, response.url):
            if url not in seen_urls and url not in fallback_urls:
                fallback_urls.append(url)

    def _crawl_html_fallback(
        self,
        first_response,
        *,
        base_params: dict[str, object],
        total_pages: int,
        seen_urls: set[str],
        fallback_urls: list[str],
    ) -> None:
        """Coleta links de todas as páginas anunciadas sem depender do JSON."""
        queue = [first_response]
        seen_page_urls = {first_response.url}
        followed_advertised_pagination = False

        while queue and len(seen_page_urls) <= 50:
            response = queue.pop(0)
            self._add_html_result_links(response, seen_urls=seen_urls, fallback_urls=fallback_urls)
            for page_url in self._html_pagination_urls(response.text, response.url):
                if page_url in seen_page_urls:
                    continue
                seen_page_urls.add(page_url)
                try:
                    page_response = self.client.get(page_url)
                except Exception as exc:
                    LOG.warning("DOU público: página HTML de contingência falhou: %s", exc)
                    continue
                followed_advertised_pagination = True
                queue.append(page_response)

        # Se o portal forneceu URLs navegáveis e elas responderam, a fila acima já
        # percorreu as páginas. Evita duplicar até 49 requisições por termo.
        if followed_advertised_pagination:
            return

        # Alguns layouts anunciam a quantidade, mas não fornecem href navegável.
        # Nesse caso, tenta cada página declarada com os parâmetros do portal.
        for page_number in range(2, min(total_pages, 50) + 1):
            generic_params = dict(base_params)
            generic_params.update({"newPage": page_number, "currentPage": page_number - 1})
            try:
                response = self.client.get(self.public_search_url, params=generic_params)
            except Exception as exc:
                LOG.warning("DOU público: página HTML %d falhou: %s", page_number, exc)
                continue
            self._add_html_result_links(response, seen_urls=seen_urls, fallback_urls=fallback_urls)

    def _collect_public(self, day: date) -> list[Document]:
        br_date = day.strftime("%d-%m-%Y")
        documents: list[Document] = []
        seen_urls: set[str] = set()
        fallback_urls: list[str] = []
        succeeded = False
        last_error: Exception | None = None

        for term in self.public_search_terms:
            base_params: dict[str, object] = {
                "q": term,
                "s": "todos",
                "exactDate": "personalizado",
                "sortType": "0",
                "delta": "200",
                "publishFrom": br_date,
                "publishTo": br_date,
            }
            try:
                response = self.client.get(self.public_search_url, params=base_params)
                succeeded = True
            except Exception as exc:
                last_error = exc
                LOG.warning("DOU público: busca por %r falhou: %s", term, exc)
                continue

            total_pages = self._page_count(response.text)
            for page_index in range(total_pages):
                records = self._public_records(response.text)
                if records is None:
                    self._crawl_html_fallback(
                        response,
                        base_params=base_params,
                        total_pages=total_pages,
                        seen_urls=seen_urls,
                        fallback_urls=fallback_urls,
                    )
                    break

                for record in records:
                    document = self._document_from_record(record, day)
                    if document and document.url not in seen_urls:
                        seen_urls.add(document.url)
                        documents.append(document)

                if page_index + 1 >= total_pages or not records:
                    break
                last = records[-1]
                record_id = last.get("classPK")
                display_date = last.get("displayDateSortable")
                if not record_id or not display_date:
                    LOG.warning("DOU público: paginação sem cursores; usando links HTML de contingência")
                    self._crawl_html_fallback(
                        response,
                        base_params=base_params,
                        total_pages=total_pages,
                        seen_urls=seen_urls,
                        fallback_urls=fallback_urls,
                    )
                    break

                page_params = dict(base_params)
                page_params.update(
                    {
                        "id": record_id,
                        "displayDate": display_date,
                        "newPage": page_index + 2,
                        "currentPage": page_index + 1,
                    }
                )
                try:
                    response = self.client.get(self.public_search_url, params=page_params)
                except Exception as exc:
                    LOG.warning("DOU público: página %d falhou: %s", page_index + 2, exc)
                    break

        if not succeeded and last_error is not None:
            raise last_error

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
