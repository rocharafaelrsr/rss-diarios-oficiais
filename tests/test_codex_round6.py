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
    title: str,
    evidence: str,
) -> FeedItem:
    return FeedItem(
        guid=guid,
        identity=guid,
        recollection_key="legacy",
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
        excerpt=evidence,
        matched_terms=["autoriza", "concurso público"],
        evidence=evidence,
    )


def _merge(old: FeedItem, new: FeedItem) -> list[FeedItem]:
    return merge_items(
        [old],
        [new],
        now=datetime(2026, 7, 27, 18, tzinfo=BRT),
        retention_days=730,
    )


def _normative_key(evidence: str, *, category: str = "ldo_concursos") -> str:
    return backend_recollection_key(
        source="dou",
        category=category,
        published_at="2026-07-27T06:00:00-03:00",
        edition="140",
        section="DO1",
        page=10,
        title="[DOU] Publicação monitorada",
        evidence=evidence,
    )


def test_complete_same_reference_from_different_issuers_is_preserved():
    old = _item(
        guid="instituto-alfa",
        link="https://www.in.gov.br/web/dou/-/portaria-1-alfa",
        title="[DOU] Autoriza novo concurso para Instituto Alfa",
        evidence="PORTARIA Nº 1. Autoriza concurso público para o Instituto Alfa.",
    )
    new = _item(
        guid="instituto-beta",
        link="https://www.in.gov.br/web/dou/-/portaria-1-beta",
        title="[DOU] Autoriza novo concurso para Instituto Beta",
        evidence="PORTARIA Nº 1. Autoriza concurso público para o Instituto Beta.",
    )

    merged = _merge(old, new)

    assert {item.guid for item in merged} == {"instituto-alfa", "instituto-beta"}


def test_complete_same_reference_and_subject_is_replaced_across_backends():
    old = _item(
        guid="inlabs",
        link="https://www.in.gov.br/consulta/-/buscar/dou?q=portaria-1",
        title="[DOU] Autoriza novo concurso para Analista Ambiental",
        evidence=(
            "PORTARIA MGI Nº 1. Autoriza a realização de concurso público para "
            "Analista Ambiental."
        ),
    )
    new = _item(
        guid="publico",
        link="https://www.in.gov.br/web/dou/-/portaria-mgi-1",
        title="[DOU] Autoriza novo concurso para cargos de Analista Ambiental",
        evidence=(
            "PORTARIA MGI Nº 1. Autoriza concurso para provimento dos cargos de "
            "Analista Ambiental."
        ),
    )

    merged = _merge(old, new)

    assert [item.guid for item in merged] == ["publico"]


def test_typographic_decree_law_dashes_are_canonicalized():
    ascii_dash = _normative_key("DECRETO-LEI Nº 100. Altera regras sobre concursos.")
    en_dash = _normative_key("DECRETO–LEI Nº 100. Altera regras sobre concursos.")
    em_dash = _normative_key("DECRETO—LEI Nº 100. Altera regras sobre concursos.")
    ordinary_law = _normative_key("LEI Nº 100. Altera regras sobre concursos.")

    assert ascii_dash == en_dash == em_dash
    assert ascii_dash != ordinary_law


def test_act_number_without_n_marker_matches_numbered_variant():
    with_marker = _normative_key(
        "PORTARIA MGI Nº 001/2026. Autoriza concurso público.",
        category="autorizacao_concurso",
    )
    without_marker = _normative_key(
        "PORTARIA MGI 1-2026. Autoriza concurso público.",
        category="autorizacao_concurso",
    )
    bare_with_marker = _normative_key(
        "PORTARIA Nº 100. Autoriza concurso público.",
        category="autorizacao_concurso",
    )
    bare_without_marker = _normative_key(
        "PORTARIA 0100. Autoriza concurso público.",
        category="autorizacao_concurso",
    )

    assert with_marker == without_marker
    assert bare_with_marker == bare_without_marker


def test_optional_number_marker_does_not_parse_year_phrase_as_act_number():
    generic_year = _normative_key(
        "A lei de 2026 estabelece diretrizes gerais para a administração pública."
    )
    numbered_law = _normative_key(
        "LEI Nº 2026. Estabelece diretrizes gerais para a administração pública."
    )

    assert generic_year != numbered_law


def test_typographic_suffix_dash_is_preserved():
    ascii_suffix = _normative_key("PORTARIA Nº 100-A. Altera regras sobre concursos.")
    en_suffix = _normative_key("PORTARIA Nº 0100–a. Altera regras sobre concursos.")
    other_suffix = _normative_key("PORTARIA Nº 100-B. Altera regras sobre concursos.")

    assert ascii_suffix == en_suffix
    assert ascii_suffix != other_suffix
