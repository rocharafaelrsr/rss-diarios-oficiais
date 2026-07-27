from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from diarios.dou_structured import StructuredDouCollector
from models import Document, FeedItem
from presentation import (
    build_presentation,
    extract_matched_act,
    recollection_key,
    sanitize_stored_items,
    stable_identity,
    strictly_relevant,
)
from state import merge_items

BRT = ZoneInfo("America/Sao_Paulo")


def _legacy_semantic_item() -> FeedItem:
    return FeedItem(
        guid="guid-v11",
        category="autorizacao_concurso",
        category_label="Autorização de novo concurso",
        priority=10,
        source="dou",
        source_label="Diário Oficial da União",
        title="[DOU] Autoriza novo concurso para Analista Ambiental",
        link="https://www.in.gov.br/web/dou/-/portaria-mgi-100#detalhes",
        published_at="2026-07-27T06:00:00-03:00",
        collected_at="2026-07-27T12:00:00-03:00",
        edition="140",
        section="DO1",
        page=10,
        excerpt="Autoriza novo concurso para Analista Ambiental.",
        matched_terms=["autoriza", "concurso público"],
    )


def test_retry_script_propagates_recollection_failure():
    script = Path(".github/scripts/publicar_estado.sh").read_text(encoding="utf-8")
    assert 'python src/main.py --source "$SOURCE" || true' not in script
    assert "retry_collection_status=$?" in script
    assert 'exit "$retry_collection_status"' in script
    assert "set -euo pipefail" in script


def test_cited_edital_is_not_treated_as_new_act_heading():
    page = (
        "PORTARIA Nº 200. Prorroga por dois anos a validade do concurso para Auditor "
        "Fiscal de Atividades Urbanas, regido pelo EDITAL Nº 01/2022, conforme os "
        "fundamentos e condições constantes do processo administrativo. "
        "EDITAL Nº 300. Abre inscrições para outro concurso público."
    )
    evidence = extract_matched_act(page, ["edital nº 01/2022"])
    assert evidence.startswith("PORTARIA Nº 200")
    assert "Prorroga por dois anos" in evidence
    assert "EDITAL Nº 300" not in evidence


def test_common_citation_prefixes_keep_enclosing_act():
    prefixes = (
        "em conformidade com o",
        "de acordo com o",
        "consoante o",
        "em observância ao",
        "na forma do",
    )
    for prefix in prefixes:
        page = (
            "PORTARIA Nº 201. Prorroga a validade do concurso para Auditor Fiscal "
            f"de Atividades Urbanas, {prefix} EDITAL Nº 01/2022, pelo prazo de dois "
            "anos, mantidas as demais disposições. EDITAL Nº 400. Abre outro certame."
        )
        evidence = extract_matched_act(page, ["edital nº 01/2022"])
        assert evidence.startswith("PORTARIA Nº 201"), prefix
        assert "Prorroga a validade" in evidence
        assert "EDITAL Nº 400" not in evidence


def test_evidence_less_legacy_item_is_replaced_by_recollection():
    legacy = _legacy_semantic_item()
    sanitized, removed = sanitize_stored_items([legacy], 2027)
    assert removed == 0
    assert len(sanitized) == 1
    assert sanitized[0].evidence == ""

    evidence = (
        "PORTARIA MGI Nº 100. Autoriza a realização de concurso público para o "
        "provimento de cargos de Analista Ambiental."
    )
    key = recollection_key(
        source="dou",
        category="autorizacao_concurso",
        published_at=legacy.published_at,
        link=legacy.link,
        page=legacy.page,
    )
    identity = stable_identity(
        source="dou",
        category="autorizacao_concurso",
        published_at=legacy.published_at,
        edition=legacy.edition,
        section=legacy.section,
        page=legacy.page,
        evidence=evidence,
    )
    recollected = FeedItem(
        guid=identity,
        identity=identity,
        recollection_key=key,
        category=legacy.category,
        category_label=legacy.category_label,
        priority=legacy.priority,
        source=legacy.source,
        source_label=legacy.source_label,
        title="[DOU] Autoriza novo concurso para cargos de Analista Ambiental",
        link=legacy.link,
        published_at=legacy.published_at,
        collected_at="2026-07-27T15:00:00-03:00",
        edition=legacy.edition,
        section=legacy.section,
        page=legacy.page,
        excerpt="Autoriza concurso para cargos de Analista Ambiental.",
        matched_terms=["autoriza", "concurso público"],
        evidence=evidence,
    )
    merged = merge_items(
        sanitized,
        [recollected],
        now=datetime(2026, 7, 27, 16, tzinfo=BRT),
        retention_days=730,
    )
    assert len(merged) == 1
    assert merged[0].evidence == evidence
    assert merged[0].guid == identity


def test_recollection_replaces_prior_version_even_with_evidence():
    legacy = _legacy_semantic_item()
    key = recollection_key(
        source=legacy.source,
        category=legacy.category,
        published_at=legacy.published_at,
        link=legacy.link,
        page=legacy.page,
    )
    old_evidence = "PORTARIA Nº 100. Autoriza concurso público de forma genérica."
    old_identity = stable_identity(
        source=legacy.source,
        category=legacy.category,
        published_at=legacy.published_at,
        edition=legacy.edition,
        section=legacy.section,
        page=legacy.page,
        evidence=old_evidence,
    )
    old = FeedItem.from_dict(
        {
            **legacy.to_dict(),
            "guid": old_identity,
            "identity": old_identity,
            "recollection_key": key,
            "evidence": old_evidence,
        }
    )

    new_evidence = (
        "PORTARIA Nº 100. Autoriza a realização de concurso público para 50 cargos "
        "de Analista Ambiental."
    )
    new_identity = stable_identity(
        source=legacy.source,
        category=legacy.category,
        published_at=legacy.published_at,
        edition=legacy.edition,
        section=legacy.section,
        page=legacy.page,
        evidence=new_evidence,
    )
    new = FeedItem.from_dict(
        {
            **legacy.to_dict(),
            "guid": new_identity,
            "identity": new_identity,
            "recollection_key": key,
            "evidence": new_evidence,
        }
    )
    merged = merge_items(
        [old],
        [new],
        now=datetime(2026, 7, 27, 16, tzinfo=BRT),
        retention_days=730,
    )
    assert len(merged) == 1
    assert merged[0].identity == new_identity
    assert merged[0].evidence == new_evidence


def test_html_fallback_follows_advertised_pagination_links_without_duplicate_requests():
    first = _Response(
        '''
        <button id="lastPage">2</button>
        <a href="/web/dou/-/ato-primeira-pagina">Ato 1</a>
        <a href="/consulta/-/buscar/dou?q=x&amp;newPage=2&amp;currentPage=1">2</a>
        <script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">
        {"jsonArray": {}}
        </script>
        '''
    )
    second = '''
        <a href="/web/dou/-/ato-segunda-pagina">Ato 2</a>
        <script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">
        {"jsonArray": {}}
        </script>
    '''
    client = _FallbackClient([second])
    collector = StructuredDouCollector(
        client,
        "https://inlabs.in.gov.br/",
        "email@example.com",
        "secret",
    )
    fallback_urls: list[str] = []
    collector._crawl_html_fallback(
        first,
        base_params={"q": "x"},
        total_pages=2,
        seen_urls=set(),
        fallback_urls=fallback_urls,
    )
    assert "https://www.in.gov.br/web/dou/-/ato-primeira-pagina" in fallback_urls
    assert "https://www.in.gov.br/web/dou/-/ato-segunda-pagina" in fallback_urls
    assert any(call[0].endswith("newPage=2&currentPage=1") for call in client.calls)
    assert not any(params and "newPage" in params for _, params in client.calls)
    assert len(client.calls) == 1


def test_authorization_negated_after_verb_is_rejected():
    cases = (
        "Autoriza o Instituto a não realizar concurso público neste exercício.",
        "Autoriza a não realização de concurso público para o órgão.",
    )
    for text in cases:
        assert not strictly_relevant(
            "autorizacao_concurso",
            "dou",
            "PORTARIA Nº 100",
            text,
            2027,
        )


def test_restrictive_sem_clause_does_not_negate_authorization():
    text = (
        "Autoriza o Instituto Brasileiro do Meio Ambiente, sem aumento de despesa, "
        "a realizar concurso público para o provimento de cargos de Analista Ambiental."
    )
    assert strictly_relevant(
        "autorizacao_concurso",
        "dou",
        "PORTARIA Nº 101",
        text,
        2027,
    )


def test_explicit_exercise_year_precedes_preferred_year_reference():
    document = Document(
        source="dou",
        source_label="Diário Oficial da União",
        title="LEI Nº 15.300, DE 20 DE JULHO DE 2026",
        url="https://www.in.gov.br/web/dou/-/lei-15300",
        published_at=datetime(2026, 7, 20, 6, tzinfo=BRT),
        text=(
            "Dispõe sobre as diretrizes para a elaboração e a execução da Lei "
            "Orçamentária para o exercício de 2026. O anexo apresenta projeções "
            "econômicas para 2027. Eu sanciono a seguinte Lei."
        ),
    )
    title, summary = build_presentation(document, "ldo", 2027)
    assert title == "[DOU] Publica a LDO federal de 2026"
    assert "2026" in summary
    assert not strictly_relevant("ldo", "dou", document.title, document.text, 2027)


def test_ldo_year_is_tied_to_budget_wording_before_later_exercise_reference():
    document = Document(
        source="dou",
        source_label="Diário Oficial da União",
        title="LEI Nº 15.301, DE 21 DE JULHO DE 2026",
        url="https://www.in.gov.br/web/dou/-/lei-15301",
        published_at=datetime(2026, 7, 21, 6, tzinfo=BRT),
        text=(
            "Dispõe sobre as diretrizes para a elaboração e a execução da Lei "
            "Orçamentária de 2027. O demonstrativo considera resultados apurados "
            "no exercício de 2025. Eu sanciono a seguinte Lei."
        ),
    )
    title, summary = build_presentation(document, "ldo", 2027)
    assert title == "[DOU] Publica a LDO federal de 2027"
    assert "2027" in summary
    assert strictly_relevant("ldo", "dou", document.title, document.text, 2027)


def test_setup_docs_name_both_split_workflows():
    readme = Path("README.md").read_text(encoding="utf-8")
    quick = Path("INSTRUCOES_RAPIDAS.md").read_text(encoding="utf-8")
    for content in (readme, quick):
        assert "Coletar DODF e DOU" not in content
        assert "Coletar DODF" in content
        assert "Coletar DOU" in content


class _Response:
    def __init__(self, text: str, url: str = "https://www.in.gov.br/consulta/-/buscar/dou"):
        self.text = text
        self.url = url


class _FallbackClient:
    def __init__(self, pages: list[str]):
        self.pages = pages
        self.calls: list[tuple[str, object]] = []

    def get(self, url: str, params=None, **kwargs):
        self.calls.append((url, params))
        text = self.pages.pop(0) if self.pages else ""
        return _Response(text, url)
