from datetime import datetime
from zoneinfo import ZoneInfo

from models import FeedItem
from recollection import _act_reference, url_recollection_key
from state import merge_items

BRT = ZoneInfo("America/Sao_Paulo")


def _item(
    *,
    guid: str,
    link: str,
    evidence: str,
    page: int | None = 10,
    title: str = "[DOU] Autoriza a realização de novo concurso público",
) -> FeedItem:
    return FeedItem(
        guid=guid,
        identity=guid,
        recollection_key="legada",
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
        page=page,
        excerpt=title,
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


def test_legacy_generic_card_requires_proven_match_before_replacement():
    old = _item(
        guid="legado-generico",
        link="https://www.in.gov.br/web/dou/-/ato-antigo",
        evidence="",
    )
    new = _item(
        guid="ato-novo-distinto",
        link="https://www.in.gov.br/web/dou/-/portaria-1-instituto-beta",
        evidence="PORTARIA Nº 1. Autoriza concurso público para o Instituto Beta.",
    )

    merged = _merge([old], [new])

    assert {item.guid for item in merged} == {"legado-generico", "ato-novo-distinto"}


def test_same_url_replaces_card_when_page_and_evidence_are_corrected():
    link = "https://www.in.gov.br/web/dou/-/portaria-mgi-100"
    old = _item(
        guid="pagina-antiga",
        link=link,
        page=10,
        evidence="EDITAL Nº 4. Trecho incorretamente tomado como ato principal.",
    )
    new = _item(
        guid="pagina-corrigida",
        link=link,
        page=11,
        evidence="PORTARIA MGI Nº 100. Autoriza concurso público para Analista Ambiental.",
        title="[DOU] Autoriza concurso para Analista Ambiental",
    )

    merged = _merge([old], [new])

    assert [item.guid for item in merged] == ["pagina-corrigida"]
    assert url_recollection_key(
        source="dou",
        category="autorizacao_concurso",
        published_at=old.published_at,
        link=link,
        page=10,
    ) == url_recollection_key(
        source="dou",
        category="autorizacao_concurso",
        published_at=new.published_at,
        link=link,
        page=11,
    )


def test_unnumbered_year_phrases_are_not_act_references():
    title = "[DOU] Altera diretrizes orçamentárias"

    assert _act_reference(title, "Dispõe sobre a lei de 1990 e seus efeitos.").startswith("semantic:")
    assert _act_reference(title, "Encaminha projeto de lei para 2026 sobre concursos.").startswith(
        "semantic:"
    )


def test_legitimate_unmarked_act_number_remains_supported():
    assert _act_reference("", "PORTARIA 2026. Autoriza concurso público.") == "portaria:2026"
