from datetime import datetime
from zoneinfo import ZoneInfo

from models import FeedItem
from recollection import backend_recollection_key
from state import merge_items

BRT = ZoneInfo("America/Sao_Paulo")


def _item(
    *,
    guid: str,
    link: str,
    evidence: str,
    title: str = "[DOU] Autoriza novo concurso para Analista Ambiental",
) -> FeedItem:
    return FeedItem(
        guid=guid,
        identity=guid,
        recollection_key="chave-antiga-baseada-na-url",
        category="autorizacao_concurso",
        category_label="Autorização de novo concurso",
        priority=10,
        source="dou",
        source_label="Diário Oficial da União",
        title=title,
        link=link,
        published_at="2026-07-27T06:00:00-03:00",
        collected_at="2026-07-27T12:00:00-03:00",
        edition="140",
        section="DO1",
        page=10,
        excerpt="Autoriza novo concurso para Analista Ambiental.",
        matched_terms=["autoriza", "concurso público"],
        evidence=evidence,
    )


def test_recollection_key_is_independent_of_backend_text_and_url():
    inlabs = backend_recollection_key(
        source="dou",
        category="autorizacao_concurso",
        published_at="2026-07-27T06:00:00-03:00",
        edition="140",
        section="DO1",
        page=10,
        title="[DOU] Autoriza novo concurso para Analista Ambiental",
        evidence=(
            "PORTARIA MGI Nº 100, DE 27 DE JULHO DE 2026. Autoriza a realização "
            "de concurso público para Analista Ambiental."
        ),
    )
    public = backend_recollection_key(
        source="dou",
        category="autorizacao_concurso",
        published_at="2026-07-27T06:00:00-03:00",
        edition="Edição 140",
        section="Seção 1",
        page=10,
        title="[DOU] Autoriza novo concurso para Analista Ambiental",
        evidence=(
            "PORTARIA MGI Nº 100, DE 27 DE JULHO DE 2026. O MINISTRO autoriza "
            "o certame para provimento dos cargos de Analista Ambiental."
        ),
    )
    assert inlabs == public


def test_public_fallback_replaces_inlabs_version_of_same_act():
    old = _item(
        guid="inlabs-guid",
        link=(
            "https://www.in.gov.br/consulta/-/buscar/dou?"
            "q=PORTARIA+MGI+N%C2%BA+100&publishFrom=27-07-2026"
        ),
        evidence=(
            "PORTARIA MGI Nº 100, DE 27 DE JULHO DE 2026. Autoriza a realização "
            "de concurso público para Analista Ambiental."
        ),
    )
    new = _item(
        guid="public-guid",
        link="https://www.in.gov.br/web/dou/-/portaria-mgi-n-100-123456",
        evidence=(
            "PORTARIA MGI Nº 100, DE 27 DE JULHO DE 2026. O Ministro de Estado "
            "autoriza a realização do concurso público para Analista Ambiental."
        ),
    )

    merged = merge_items(
        [old],
        [new],
        now=datetime(2026, 7, 27, 18, tzinfo=BRT),
        retention_days=730,
    )

    assert len(merged) == 1
    assert merged[0].guid == "public-guid"
    assert merged[0].link.endswith("portaria-mgi-n-100-123456")
    assert merged[0].recollection_key != "chave-antiga-baseada-na-url"


def test_numbered_acts_on_same_page_do_not_collide():
    first = _item(
        guid="portaria-100",
        link="https://www.in.gov.br/web/dou/-/portaria-100",
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
    )
    second = _item(
        guid="portaria-101",
        link="https://www.in.gov.br/web/dou/-/portaria-101",
        evidence="PORTARIA MGI Nº 101. Autoriza concurso público para Analista Ambiental.",
    )

    merged = merge_items(
        [first],
        [second],
        now=datetime(2026, 7, 27, 18, tzinfo=BRT),
        retention_days=730,
    )

    assert {item.guid for item in merged} == {"portaria-100", "portaria-101"}
