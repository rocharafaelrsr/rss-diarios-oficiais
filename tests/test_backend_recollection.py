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
    edition: str = "140",
    section: str = "DO1",
    page: int | None = 10,
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
        edition=edition,
        section=section,
        page=page,
        excerpt="Autoriza novo concurso para Analista Ambiental.",
        matched_terms=["autoriza", "concurso público"],
        evidence=evidence,
    )


def _merge(old: list[FeedItem], new: list[FeedItem]) -> list[FeedItem]:
    return merge_items(
        old,
        new,
        now=datetime(2026, 7, 27, 18, tzinfo=BRT),
        retention_days=730,
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

    merged = _merge([old], [new])

    assert len(merged) == 1
    assert merged[0].guid == "public-guid"
    assert merged[0].link.endswith("portaria-mgi-n-100-123456")
    assert merged[0].recollection_key != "chave-antiga-baseada-na-url"


def test_missing_public_metadata_uses_normative_reference_fallback():
    old = _item(
        guid="inlabs-completo",
        link="https://www.in.gov.br/consulta/-/buscar/dou?q=portaria-100",
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
    )
    new = _item(
        guid="public-incompleto",
        link="https://www.in.gov.br/web/dou/-/portaria-mgi-100",
        evidence="PORTARIA MGI N° 0100. Autoriza o concurso para Analista Ambiental.",
        edition="",
        section="",
        page=None,
    )

    merged = _merge([old], [new])

    assert [item.guid for item in merged] == ["public-incompleto"]


def test_complete_suffixed_editions_remain_distinct():
    regular = _item(
        guid="edicao-140",
        link="https://www.in.gov.br/web/dou/-/portaria-100-regular",
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
        edition="140",
    )
    extra = _item(
        guid="edicao-140-a",
        link="https://www.in.gov.br/web/dou/-/portaria-100-extra",
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
        edition="140-A",
    )

    merged = _merge([regular], [extra])

    assert {item.guid for item in merged} == {"edicao-140", "edicao-140-a"}


def test_complete_suffixed_sections_remain_distinct():
    regular = _item(
        guid="secao-do1",
        link="https://www.in.gov.br/web/dou/-/portaria-100-do1",
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
        section="DO1",
    )
    extra = _item(
        guid="secao-do1e",
        link="https://www.in.gov.br/web/dou/-/portaria-100-do1e",
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
        section="DO1E",
    )

    merged = _merge([regular], [extra])

    assert {item.guid for item in merged} == {"secao-do1", "secao-do1e"}


def test_act_number_notations_are_canonicalized():
    variants = (
        "PORTARIA MGI Nº 001/2026. Autoriza concurso público.",
        "PORTARIA MGI N° 1-2026. Autoriza concurso público.",
        "PORTARIA MGI N 01 / 2026. Autoriza concurso público.",
    )
    keys = {
        backend_recollection_key(
            source="dou",
            category="autorizacao_concurso",
            published_at="2026-07-27T06:00:00-03:00",
            edition="140",
            section="DO1",
            page=10,
            title="[DOU] Autoriza novo concurso",
            evidence=evidence,
        )
        for evidence in variants
    }
    assert len(keys) == 1


def test_accented_heading_is_preferred_over_later_citations():
    first = backend_recollection_key(
        source="dou",
        category="atub",
        published_at="2026-07-27T06:00:00-03:00",
        edition="140",
        section="DO1",
        page=10,
        title="[DOU] Publica edital",
        evidence=(
            "EDITAL DE CONVOCAÇÃO Nº 1. Convoca os candidatos, nos termos da "
            "LEI Nº 123, para apresentação de documentos."
        ),
    )
    second = backend_recollection_key(
        source="dou",
        category="atub",
        published_at="2026-07-27T06:00:00-03:00",
        edition="Edição 140",
        section="Seção 1",
        page=10,
        title="[DOU] Publica edital",
        evidence=(
            "EDITAL DE CONVOCACAO N° 01. Convoca os candidatos com fundamento "
            "na LEI Nº 999 e em demais normas aplicáveis."
        ),
    )
    assert first == second


def test_same_url_replaces_item_when_corrected_extraction_changes_reference():
    link = "https://www.in.gov.br/web/dou/-/portaria-mgi-100"
    old = _item(
        guid="recorte-antigo",
        link=link,
        evidence=(
            "EDITAL Nº 4/2025. Trecho citado que antes foi tomado como início do ato. "
            "PORTARIA MGI Nº 100. Prorroga a validade do concurso público."
        ),
    )
    new = _item(
        guid="recorte-corrigido",
        link=link,
        evidence=(
            "PORTARIA MGI Nº 100. Prorroga a validade do concurso público regido "
            "pelo EDITAL Nº 4/2025."
        ),
    )

    merged = _merge([old], [new])

    assert [item.guid for item in merged] == ["recorte-corrigido"]


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

    merged = _merge([first], [second])

    assert {item.guid for item in merged} == {"portaria-100", "portaria-101"}


def test_alphabetic_act_suffixes_are_preserved_and_canonicalized():
    def key(evidence: str) -> str:
        return backend_recollection_key(
            source="dou",
            category="autorizacao_concurso",
            published_at="2026-07-27T06:00:00-03:00",
            edition="140",
            section="DO1",
            page=10,
            title="[DOU] Autoriza novo concurso",
            evidence=evidence,
        )

    suffix_a = key("PORTARIA Nº 100-A. Autoriza concurso público.")
    suffix_a_variant = key("PORTARIA N° 0100-a. Autoriza concurso público.")
    suffix_b = key("PORTARIA Nº 100-B. Autoriza concurso público.")

    assert suffix_a == suffix_a_variant
    assert suffix_a != suffix_b


def test_decree_law_is_distinct_from_ordinary_law():
    common = {
        "source": "dou",
        "category": "ldo_concursos",
        "published_at": "2026-07-27T06:00:00-03:00",
        "edition": "140",
        "section": "DO1",
        "page": 10,
        "title": "[DOU] Altera norma sobre concursos",
    }
    decree_law = backend_recollection_key(
        **common,
        evidence="DECRETO-LEI Nº 100. Altera regras sobre concursos públicos.",
    )
    ordinary_law = backend_recollection_key(
        **common,
        evidence="LEI Nº 100. Altera regras sobre concursos públicos.",
    )

    assert decree_law != ordinary_law
