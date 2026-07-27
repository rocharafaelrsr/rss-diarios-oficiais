from __future__ import annotations

import io
import logging
import os
import re
import time as time_module
import zipfile
from datetime import date, datetime, time
from html import unescape
from urllib.parse import quote_plus, urljoin
from defusedxml import ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from http_client import HttpClient
from models import Document
from text_utils import clean_text

LOG = logging.getLogger(__name__)
BRT = ZoneInfo("America/Sao_Paulo")


class InlabsAuthenticationError(RuntimeError):
    pass


class DouCollector:
    """Coleta os XMLs oficiais do DOU no Portal INLABS.

    O fluxo segue o protocolo usado pelo projeto governamental Ro-DOU:
    autenticação em logar.php, listagem em index.php?p=AAAA-MM-DD e download
    dos ZIPs anunciados como "Baixar Arquivo".
    """

    def __init__(self, client: HttpClient, base_url: str, email: str, password: str) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/") + "/"
        self.email = email.strip()
        self.password = password
        self._logged_in = False

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
                # Cria cookies e contexto de navegação antes do POST. Alguns
                # servidores encerram conexões diretas de datacenters sem esse passo.
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
            # Os links normalmente são ?dl=arquivo.zip e devem ser resolvidos
            # contra index.php, não apenas contra a raiz.
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
            # O campo texto/body contém HTML. itertext preserva o conteúdo útil.
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

    def collect(self, day: date) -> list[Document]:
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
