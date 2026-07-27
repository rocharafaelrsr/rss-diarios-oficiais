from __future__ import annotations

import io
import logging
import re
import time as time_module
import zipfile
from datetime import date, datetime, time
from html import unescape
from urllib.parse import quote_plus, urljoin, urlparse
from defusedxml import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from http_client import HttpClient
from models import Document
from text_utils import clean_text

LOG = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")
IN_HOSTS = {"in.gov.br", "www.in.gov.br"}
DEFAULT_PUBLIC_TERMS = (
    '"lei de diretrizes orçamentárias"',
    '"diretrizes orçamentárias"',
    '"concurso público"',
    '"autorização de concurso"',
    "LDO",
)


class InlabsAuthenticationError(RuntimeError):
    pass


class DouCollector:
    """Coleta o DOU pelo INLABS e usa a busca pública oficial como fallback."""

    def __init__(
        self,
        client: HttpClient,
        base_url: str,
        email: str,
        password: str,
        public_search_url: str = "https://www.in.gov.br/consulta/-/buscar/dou",
        public_search_terms: list[str] | tuple[str, ...] | None = None,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/") + "/"
        self.email = email.strip()
        self.password = password
        self.public_search_url = public_search_url
        self.public_search_terms = tuple(public_search_terms or DEFAULT_PUBLIC_TERMS)
        self._logged_in = False
        self.backend = "inlabs"
        self.fallback_reason = ""

    def _login(self) -> None:
        if self._logged_in and self.client.session.cookies.get("inlabs_session_cookie"):
            return
        if not self.email or not self.password:
            raise InlabsAuthenticationError(
                "Credenciais do INLABS ausentes. Configure INLABS_EMAIL e INLABS_PASSWORD."
            )

        login_url = urljoin(self.base_url, "logar.php")
        referer = urljoin(self.base_url, "acessar.php")
        last_error: Exception | None = None
        for attempt in range(1, 3):
            try:
                self.client.get(self.base_url)
                response = self.client.session.post(
                    login_url,
                    data={"email": self.email, "password": self.password},
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Origin": self.base_url.rstrip("/"),
                        "Referer": referer,
                    },
                    timeout=self.client.request_timeout,
                )
                response.raise_for_status()
                if not self.client.session.cookies.get("inlabs_session_cookie"):
                    raise InlabsAuthenticationError("Autenticação no INLABS recusada.")
                self._logged_in = True
                return
            except InlabsAuthenticationError:
                raise
            except Exception as exc:
                last_error = exc
                LOG.warning("INLABS: tentativa de login %d/2 falhou: %s", attempt, exc)
                if attempt < 2:
                    time_module.sleep(2.5)
        raise ConnectionError(f"INLABS indisponível durante o login: {last_error}") from last_error

    def _zip_urls(self, day: date) -> list[str]:
        self._login()
        cookie = self.client.session.cookies.get("inlabs_session_cookie", "")
        response = self.client.get(
            urljoin(self.base_url, "index.php"),
            params={"p": day.isoformat()},
            headers={
                "Cookie": f"inlabs_session_cookie={cookie}",
                "origem": "736372697074",
            },
        )
        soup = BeautifulSoup(response.text, "html.parser")
        urls: list[str] = []
        for anchor in soup.find_all("a", title="Baixar Arquivo"):
            href = str(anchor.get("href", ""))
            if not href.lower().endswith(".zip") and ".zip" not in href.lower():
                continue
            absolute = urljoin(urljoin(self.base_url, "index.php"), href)
            if absolute not in urls:
                urls.append(absolute)
        if not urls:
            LOG.warning("INLABS %s: nenhum ZIP listado", day.isoformat())
        return urls

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1].casefold()

    @classmethod
    def _xml_values(cls, root: ET.Element) -> dict[str, str]:
        values = {str(k).casefold(): clean_text(str(v)) for k, v in root.attrib.items()}
        for node in root.iter():
            key = cls._local_name(node.tag)
            if key == cls._local_name(root.tag):
                continue
            value = clean_text(" ".join(node.itertext()))
            if value and (key not in values or len(value) > len(values[key])):
                values[key] = value
        return values

    @staticmethod
    def _first(values: dict[str, str], *keys: str) -> str:
        for key in keys:
            value = values.get(key.casefold(), "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _int_or_none(value: str) -> int | None:
        match = re.search(r"\d+", value or "")
        return int(match.group()) if match else None

    @staticmethod
    def _public_search_link(title: str, day: date) -> str:
        br_date = day.strftime("%d-%m-%Y")
        return (
            "https://www.in.gov.br/consulta/-/buscar/dou"
            f"?q={quote_plus(title)}&s=todos&exactDate=personalizado&sortType=0"
            f"&publishFrom={br_date}&publishTo={br_date}"
        )

    def _document_from_xml(self, payload: bytes, day: date, filename: str) -> Document | None:
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            LOG.warning("INLABS: XML inválido em %s", filename)
            return None
        values = self._xml_values(root)
        title = self._first(values, "name", "identifica", "titulo", "ementa")
        text_fields = [
            self._first(values, "identifica"),
            self._first(values, "ementa"),
            self._first(values, "titulo"),
            self._first(values, "subtitulo"),
            self._first(values, "texto", "body"),
            self._first(values, "assina"),
        ]
        raw_text = unescape(" ".join(part for part in text_fields if part))
        text_value = clean_text(BeautifulSoup(raw_text, "html.parser").get_text(" ", strip=True))
        if not text_value:
            return None

        published = datetime.combine(day, time(hour=6), tzinfo=BRT)
        raw_date = self._first(values, "pubdate", "publishdate", "data")
        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
            try:
                published = datetime.strptime(raw_date[:10], fmt).replace(tzinfo=BRT)
                break
            except (ValueError, TypeError):
                continue

        section = self._first(values, "pubname", "section", "secao")
        edition = self._first(values, "editionnumber", "edition", "edicao")
        page = self._int_or_none(self._first(values, "numberpage", "pdfpage", "pagina"))
        display_title = title or f"Matéria do DOU ({filename})"
        return Document(
            source="dou",
            source_label="Diário Oficial da União",
            title=display_title,
            url=self._public_search_link(display_title, day),
            published_at=published,
            text=text_value,
            edition=edition,
            section=section,
            page=page,
        )

    def _collect_inlabs(self, day: date) -> list[Document]:
        documents: list[Document] = []
        cookie_headers = {"origem": "736372697074"}
        for zip_url in self._zip_urls(day):
            try:
                response = self.client.get(zip_url, headers=cookie_headers)
                archive = zipfile.ZipFile(io.BytesIO(response.content))
            except Exception:
                LOG.exception("INLABS: falha ao baixar/abrir %s", zip_url)
                continue
            with archive:
                total_uncompressed = sum(member.file_size for member in archive.infolist())
                if total_uncompressed > 500 * 1024 * 1024:
                    LOG.error("INLABS: ZIP rejeitado por tamanho descompactado excessivo: %s", zip_url)
                    continue
                for member in archive.infolist():
                    if member.is_dir() or not member.filename.lower().endswith(".xml"):
                        continue
                    if member.file_size > 20 * 1024 * 1024:
                        LOG.warning("INLABS: XML excessivamente grande ignorado: %s", member.filename)
                        continue
                    try:
                        payload = archive.read(member)
                    except Exception:
                        LOG.exception("INLABS: falha ao ler %s", member.filename)
                        continue
                    document = self._document_from_xml(payload, day, member.filename)
                    if document:
                        documents.append(document)
        return documents

    @staticmethod
    def _public_result_links(html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href", ""))
            if "/web/dou/-/" not in href and "/en/web/dou/-/" not in href:
                continue
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)
            if parsed.scheme != "https" or (parsed.hostname or "").casefold() not in IN_HOSTS:
                continue
            canonical = absolute.replace(
                "https://www.in.gov.br/en/web/dou/-/",
                "https://www.in.gov.br/web/dou/-/",
            )
            canonical = canonical.replace(
                "https://in.gov.br/en/web/dou/-/",
                "https://www.in.gov.br/web/dou/-/",
            )
            canonical = canonical.replace(
                "https://in.gov.br/web/dou/-/",
                "https://www.in.gov.br/web/dou/-/",
            )
            if canonical not in urls:
                urls.append(canonical)
        return urls

    def _public_urls(self, day: date) -> list[str]:
        br_date = day.strftime("%d-%m-%Y")
        urls: list[str] = []
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
                        "delta": "200",
                        "publishFrom": br_date,
                        "publishTo": br_date,
                    },
                )
                succeeded = True
            except Exception as exc:
                last_error = exc
                LOG.warning("DOU público: busca por %r falhou: %s", term, exc)
                continue
            for url in self._public_result_links(response.text, response.url):
                if url not in urls:
                    urls.append(url)
        if not succeeded and last_error is not None:
            raise last_error
        return urls

    @staticmethod
    def _article_container(soup: BeautifulSoup):
        selectors = (
            ".texto-dou",
            "#texto-dou",
            ".journal-content-article",
            ".materia",
            "article",
            "main",
        )
        candidates = []
        for selector in selectors:
            candidates.extend(soup.select(selector))
        if not candidates:
            return soup.body or soup
        return max(candidates, key=lambda node: len(clean_text(node.get_text(" ", strip=True))))

    @classmethod
    def _document_from_public_html(cls, html: str, url: str, day: date) -> Document | None:
        soup = BeautifulSoup(html, "html.parser")
        whole_text = clean_text(soup.get_text(" ", strip=True))
        metadata = re.search(
            r"Publicado em:\s*(\d{2}/\d{2}/\d{4})\s*\|\s*Edição:\s*([^|]+?)\s*\|\s*Seção:\s*([^|]+?)\s*\|\s*Página:\s*(\d+)",
            whole_text,
            flags=re.I,
        )
        if not metadata:
            LOG.warning("DOU público: metadados não encontrados em %s", url)
            return None
        try:
            published_day = datetime.strptime(metadata.group(1), "%d/%m/%Y").date()
        except ValueError:
            return None
        if published_day != day:
            return None

        title = ""
        for selector in ("h2", "h1", ".title", ".titulo"):
            for node in soup.select(selector):
                value = clean_text(node.get_text(" ", strip=True))
                if value and "publicador de conteúdos" not in value.casefold() and len(value) > 4:
                    title = value
                    break
            if title:
                break
        if not title and soup.title:
            title = clean_text(soup.title.get_text(" ", strip=True).split(" - DOU")[0])
        if not title:
            title = "Matéria do Diário Oficial da União"

        container = cls._article_container(soup)
        text_value = clean_text(container.get_text(" ", strip=True))
        if len(text_value) < 80:
            return None
        page = int(metadata.group(4))
        return Document(
            source="dou",
            source_label="Diário Oficial da União",
            title=title,
            url=url,
            published_at=datetime.combine(day, time(hour=6), tzinfo=BRT),
            text=text_value,
            edition=clean_text(metadata.group(2)),
            section=clean_text(metadata.group(3)),
            page=page,
        )

    def _collect_public(self, day: date) -> list[Document]:
        documents: list[Document] = []
        for url in self._public_urls(day):
            try:
                response = self.client.get(url)
                document = self._document_from_public_html(response.text, response.url, day)
            except Exception as exc:
                LOG.warning("DOU público: falha ao abrir %s: %s", url, exc)
                continue
            if document:
                documents.append(document)
        return documents

    def collect(self, day: date) -> list[Document]:
        try:
            documents = self._collect_inlabs(day)
            if documents:
                self.backend = "inlabs"
                return documents
            primary_error: Exception = RuntimeError("INLABS sem documentos para a data")
        except Exception as exc:
            primary_error = exc
        self.fallback_reason = str(primary_error)[:500]
        LOG.warning("DOU %s: acionando busca pública oficial: %s", day.isoformat(), primary_error)
        try:
            documents = self._collect_public(day)
        except Exception as fallback_error:
            raise RuntimeError(
                f"INLABS e busca pública do DOU indisponíveis: primário={primary_error}; fallback={fallback_error}"
            ) from fallback_error
        self.backend = "busca_publica"
        LOG.info("DOU %s: busca pública retornou %d documentos", day.isoformat(), len(documents))
        return documents
