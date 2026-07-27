from datetime import date

from diarios.dou import DouCollector


class DummyClient:
    pass


def test_parse_inlabs_xml():
    collector = DouCollector(DummyClient(), "https://inlabs.in.gov.br/", "x@y.z", "secret")
    payload = b'''<?xml version="1.0" encoding="UTF-8"?>
    <article id="123" name="PORTARIA N. 10" pubName="DO1" pubDate="27/07/2026"
             numberPage="15" editionNumber="140">
      <identifica>PORTARIA N. 10, DE 26 DE JULHO DE 2026</identifica>
      <ementa>Autoriza a realiza\xc3\xa7\xc3\xa3o de concurso p\xc3\xbablico.</ementa>
      <body><p class="texto-dou">Fica autorizada a realiza\xc3\xa7\xc3\xa3o do certame.</p></body>
    </article>'''
    doc = collector._document_from_xml(payload, date(2026, 7, 27), "DO1.xml")
    assert doc is not None
    assert doc.title == "PORTARIA N. 10"
    assert "concurso" in doc.text
    assert doc.section == "DO1"
    assert doc.page == 15
    assert "publishFrom=27-07-2026" in doc.url


class LoginResponse:
    def raise_for_status(self):
        return None


class LoginSession:
    def __init__(self):
        self.cookies = {}
        self.posts = 0

    def post(self, *_args, **_kwargs):
        self.posts += 1
        self.cookies["inlabs_session_cookie"] = "ok"
        return LoginResponse()


class LoginClient:
    timeout = 30
    request_timeout = (10, 30)

    def __init__(self):
        self.session = LoginSession()
        self.gets = 0

    def get(self, *_args, **_kwargs):
        self.gets += 1
        return LoginResponse()


def test_login_is_reused_between_dates():
    client = LoginClient()
    collector = DouCollector(client, "https://inlabs.in.gov.br/", "x@y.z", "secret")
    collector._login()
    collector._login()
    assert client.session.posts == 1
    assert client.gets == 1
