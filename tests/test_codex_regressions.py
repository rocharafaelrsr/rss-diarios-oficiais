from datetime import date, datetime
from zoneinfo import ZoneInfo

from diarios.dou_structured import StructuredDouCollector
from main import classify, expand_rule_tokens, load_config
from models import Document, FeedItem
from presentation import (
    build_presentation,
    extract_matched_act,
    sanitize_stored_items,
    stable_identity,
    strictly_relevant,
)
from rules import Rule
from state import merge_items

BRT = ZoneInfo("America/Sao_Paulo")


def test_semantic_ldo_item_survives_repeated_sanitization():
    evidence = (
        "LEI Nº 15.100, DE 20 DE JULHO DE 2026. Dispõe sobre as diretrizes "
        "para a elaboração e a execução da Lei Orçamentária de 2027. Eu sanciono."
    )
    item = FeedItem(
        guid="legacy",
        category="ldo",
        category_label="Publicação da LDO",
        priority=10,
        source="dou",
        source_label="Diário Oficial da União",
        title="[DOU] Publica a LDO federal de 2027",
        link="https://www.in.gov.br/web/dou/-/lei-15100",
        published_at="2026-07-20T06:00:00-03:00",
        collected_at="2026-07-20T12:00:00-03:00",
        edition="140",
        section="DO1",
        page=1,
        excerpt="A publicação estabelece as diretrizes orçamentárias federais para 2027.",
        matched_terms=["diretrizes", "2027"],
        evidence=evidence,
    )
    first, removed_first = sanitize_stored_items([item], 2027)
    second, removed_second = sanitize_stored_items(first, 2027)
    assert removed_first == removed_second == 0
    assert len(second) == 1
    assert second[0].title.endswith("2027")
    assert second[0].evidence == evidence


def test_ldo_title_prefers_exercise_year_over_publication_year():
    document = Document(
        source="dou",
        source_label="Diário Oficial da União",
        title="LEI Nº 15.100, DE 20 DE JULHO DE 2026",
        url="https://www.in.gov.br/web/dou/-/lei-15100",
        published_at=datetime(2026, 7, 20, 6, tzinfo=BRT),
        text=(
            "Dispõe sobre as diretrizes para a elaboração e a execução da Lei "
            "Orçamentária de 2027. Esta Lei estabelece as diretrizes orçamentárias."
        ),
    )
    title, summary = build_presentation(document, "ldo", 2027)
    assert title == "[DOU] Publica a LDO federal de 2027"
    assert "2027" in summary
    assert "LDO federal de 2026" not in title


def test_legacy_guid_is_migrated_and_deduplicated():
    evidence = (
        "PORTARIA MGI Nº 100. Autoriza a realização de concurso público para o "
        "provimento de 50 cargos de Analista Ambiental."
    )
    legacy = FeedItem(
        guid="old-summary-guid",
        category="autorizacao_concurso",
        category_label="Autorização de novo concurso",
        priority=10,
        source="dou",
        source_label="Diário Oficial da União",
        title="PORTARIA MGI Nº 100",
        link="https://www.in.gov.br/web/dou/-/portaria-100",
        published_at="2026-07-27T06:00:00-03:00",
        collected_at="2026-07-27T12:00:00-03:00",
        edition="140",
        section="DO1",
        page=10,
        excerpt=evidence,
        matched_terms=["autoriza", "concurso público"],
    )
    migrated, removed = sanitize_stored_items([legacy], 2027)
    assert removed == 0
    assert migrated[0].guid == migrated[0].identity
    assert migrated[0].guid != "old-summary-guid"

    identity = stable_identity(
        source="dou",
        category="autorizacao_concurso",
        published_at=legacy.published_at,
        edition="140",
        section="DO1",
        page=10,
        evidence=evidence,
    )
    recollected = FeedItem.from_dict({**migrated[0].to_dict(), "guid": identity, "identity": identity})
    merged = merge_items(
        migrated,
        [recollected],
        now=datetime(2026, 7, 27, 15, tzinfo=BRT),
        retention_days=730,
    )
    assert len(merged) == 1


def test_authorization_with_agency_between_verb_and_action_matches_config():
    config = load_config(__import__("pathlib").Path("config/monitors.yml"))
    rules = [Rule.from_dict(value) for value in expand_rule_tokens(config["rules"], next_year=2027)]
    rule = next(value for value in rules if value.id == "autorizacao_concurso")
    text = "Autoriza o Instituto Brasileiro do Meio Ambiente a realizar concurso público para Analista Ambiental."
    assert rule.match("dou", text)
    assert strictly_relevant("autorizacao_concurso", "dou", "PORTARIA MGI Nº 100", text, 2027)


def test_negated_authorization_is_rejected():
    text = "O parecer conclui por não autorizar a realização de concurso público neste exercício."
    assert not strictly_relevant("autorizacao_concurso", "dou", "PARECER Nº 10", text, 2027)


def test_canonical_ldo_wording_is_recognized():
    text = (
        "LEI Nº 15.200, DE 20 DE JULHO DE 2026. Dispõe sobre as diretrizes para a "
        "elaboração e a execução da Lei Orçamentária de 2027. Faço saber que o "
        "Congresso Nacional decreta e eu sanciono a seguinte Lei."
    )
    assert strictly_relevant("ldo", "dou", "LEI Nº 15.200, DE 20 DE JULHO DE 2026", text, 2027)


def test_matched_act_isolated_from_other_act_on_same_dodf_page():
    page = (
        "EDITAL Nº 10. Convoca candidatos de outro certame para curso de formação. "
        "PORTARIA Nº 200. Prorroga a validade do concurso para Auditor Fiscal de "
        "Atividades Urbanas pelo prazo de dois anos. "
        "EDITAL Nº 11. Publica resultado de concurso para Técnico Administrativo."
    )
    evidence = extract_matched_act(page, ["auditor fiscal de atividades urbanas", "prorroga"])
    assert evidence.startswith("PORTARIA Nº 200")
    assert "outro certame" not in evidence
    assert "Técnico Administrativo" not in evidence

    rule = Rule.from_dict(
        {
            "id": "atub",
            "label": "Concurso ATUB",
            "sources": ["dodf"],
            "priority": 10,
            "any_phrases": ["auditor fiscal de atividades urbanas"],
            "context_any": ["prorroga"],
        }
    )
    document = Document(
        source="dodf",
        source_label="Diário Oficial do Distrito Federal",
        title="DODF 140 — página 20",
        url="https://www.sinj.df.gov.br/diario#page=20",
        published_at=datetime(2026, 7, 27, 6, tzinfo=BRT),
        text=page,
        edition="DODF 140",
        page=20,
    )
    items = classify([document], [rule], datetime(2026, 7, 27, 15, tzinfo=BRT), next_year=2027)
    assert len(items) == 1
    assert items[0].title == "[DODF] Prorroga a validade do concurso ATUB"
    assert "outro certame" not in items[0].evidence


def test_structured_json_wrong_shape_activates_fallback():
    wrong_shapes = (
        '<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">{"other":[]}</script>',
        '<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">{"jsonArray":{}}</script>',
        '<script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">{"jsonArray":["bad"]}</script>',
    )
    for html in wrong_shapes:
        assert StructuredDouCollector._public_records(html) is None


class _Response:
    def __init__(self, text: str, url: str = "https://www.in.gov.br/consulta/-/buscar/dou"):
        self.text = text
        self.url = url


class _Client:
    def __init__(self, pages: list[str]):
        self.pages = pages
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, params=None, **kwargs):
        self.calls.append(dict(params or {}))
        return _Response(self.pages.pop(0), url)


def _result_page(title: str, slug: str, record_id: str, *, last_page: int | None = None) -> str:
    button = f'<button id="lastPage">{last_page}</button>' if last_page else ""
    return f'''
    {button}
    <script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">
    {{"jsonArray":[{{"pubName":"DO1","title":"{title}","urlTitle":"{slug}",
    "content":"Autoriza a realização de concurso público para Analista Ambiental.",
    "pubDate":"27/07/2026","classPK":"{record_id}",
    "displayDateSortable":"20260727","hierarchyStr":"Ministério da Gestão",
    "artType":"Portaria"}}]}}
    </script>
    '''


def test_structured_search_requests_all_pages_and_large_delta():
    client = _Client(
        [
            _result_page("PORTARIA Nº 1", "portaria-1", "1", last_page=2),
            _result_page("PORTARIA Nº 2", "portaria-2", "2"),
        ]
    )
    collector = StructuredDouCollector(
        client,
        "https://inlabs.in.gov.br/",
        "email@example.com",
        "secret",
        public_search_terms=["autoriza AND concurso"],
    )
    documents = collector._collect_public(date(2026, 7, 27))
    assert len(documents) == 2
    assert client.calls[0]["delta"] == "200"
    assert client.calls[1]["newPage"] == 2
    assert client.calls[1]["currentPage"] == 1
