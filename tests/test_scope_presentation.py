from datetime import date, datetime
from zoneinfo import ZoneInfo

from diarios.dou_structured import StructuredDouCollector
from models import Document, FeedItem
from presentation import build_presentation, sanitize_stored_items, strictly_relevant
from rules import Rule

BRT = ZoneInfo("America/Sao_Paulo")


FALSE_LDO = """
EDITAL Nº 44, DE 22 DE JUNHO DE 2026
RETIFICAÇÃO DO EDITAL Nº 39/2026. Homologação do Resultado do Concurso para
Professor do Magistério Superior da Universidade Federal do Ceará. O Reitor
retifica a homologação do resultado final do Concurso Público regido pelo
Edital nº 04/2025, conforme anexos do processo administrativo.
"""


def test_ldo_is_not_found_inside_unrelated_words():
    rule = Rule.from_dict(
        {
            "id": "ldo_concursos",
            "label": "LDO",
            "sources": ["dou"],
            "priority": 10,
            "all_groups": [[" ldo "], ["concurso público"], ["retifica"]],
        }
    )
    assert rule.match("dou", FALSE_LDO) is None


def test_university_contest_is_outside_ldo_scope():
    assert not strictly_relevant(
        "ldo_concursos",
        "dou",
        "EDITAL Nº 44, DE 22 DE JUNHO DE 2026",
        FALSE_LDO,
        2027,
    )


def test_actual_ldo_change_about_contests_is_relevant():
    text = """
    LEI Nº 15.100, DE 27 DE JULHO DE 2026. Altera a Lei de Diretrizes
    Orçamentárias para o exercício de 2027 e acrescenta dispositivo ao anexo de
    pessoal para autorizar provimentos decorrentes de concurso público.
    """
    assert strictly_relevant("ldo_concursos", "dou", "LEI Nº 15.100", text, 2027)


def test_nomination_based_on_old_authorization_is_not_new_contest_authorization():
    text = """
    PORTARIA Nº 785. Com base nas autorizações concedidas anteriormente, resolve
    nomear candidata aprovada em concurso público para cargo efetivo.
    """
    assert not strictly_relevant("autorizacao_concurso", "dou", "PORTARIA Nº 785", text, 2027)


def test_explicit_new_contest_authorization_is_relevant():
    text = """
    PORTARIA MGI Nº 100. Autoriza a realização de concurso público para o
    provimento de 200 cargos de Analista Ambiental do Instituto Brasileiro do
    Meio Ambiente e dos Recursos Naturais Renováveis.
    """
    assert strictly_relevant("autorizacao_concurso", "dou", "PORTARIA MGI Nº 100", text, 2027)


def test_semantic_title_and_short_summary_for_authorization():
    document = Document(
        source="dou",
        source_label="Diário Oficial da União",
        title="PORTARIA MGI Nº 100, DE 27 DE JULHO DE 2026",
        url="https://www.in.gov.br/web/dou/-/portaria-100",
        published_at=datetime(2026, 7, 27, 6, tzinfo=BRT),
        text=(
            "PORTARIA MGI Nº 100, DE 27 DE JULHO DE 2026. Autoriza a realização "
            "de concurso público para o provimento de 200 cargos de Analista "
            "Ambiental do Ibama."
        ),
        organization="Ministério da Gestão e da Inovação em Serviços Públicos",
    )
    title, summary = build_presentation(document, "autorizacao_concurso", 2027)
    assert title.startswith("[DOU] Autoriza novo concurso para")
    assert "Analista Ambiental" in title
    assert len(title) <= 112
    assert "Autoriza a realização" in summary
    assert len(summary) <= 300


def test_semantic_title_for_atub_course():
    document = Document(
        source="dodf",
        source_label="Diário Oficial do Distrito Federal",
        title="EDITAL Nº 20",
        url="https://www.sinj.df.gov.br/ato",
        published_at=datetime(2026, 7, 27, 6, tzinfo=BRT),
        text=(
            "Convoca os candidatos aprovados no concurso para Auditor Fiscal de "
            "Atividades Urbanas para matrícula no curso de formação profissional."
        ),
    )
    title, summary = build_presentation(document, "atub", 2027)
    assert title == "[DODF] Convoca candidatos do concurso ATUB para o curso de formação"
    assert "Convoca" in summary


def test_public_dou_structured_json_is_parsed():
    html = '''
    <script id="_br_com_seatecnologia_in_buscadou_BuscaDouPortlet_params">
    {"jsonArray":[{"pubName":"DO1","title":"PORTARIA MGI Nº 100",
    "urlTitle":"portaria-mgi-n-100-123", "content":"Autoriza a realização de concurso público para Analista Ambiental.",
    "pubDate":"27/07/2026", "classPK":"123", "displayDateSortable":"20260727",
    "hierarchyStr":"Ministério da Gestão", "artType":"Portaria", "numberPage":"10",
    "editionNumber":"140"}]}
    </script>
    '''
    records = StructuredDouCollector._public_records(html)
    assert records is not None and len(records) == 1
    document = StructuredDouCollector._document_from_record(records[0], date(2026, 7, 27))
    assert document is not None
    assert document.url == "https://www.in.gov.br/web/dou/-/portaria-mgi-n-100-123"
    assert document.organization == "Ministério da Gestão"
    assert document.publication_type == "Portaria"
    assert document.page == 10


def test_stored_false_positives_are_removed():
    item = FeedItem(
        guid="x",
        category="ldo_concursos",
        category_label="Alteração da LDO sobre concursos",
        priority=10,
        source="dou",
        source_label="Diário Oficial da União",
        title="[DOU] Alteração da LDO sobre concursos | EDITAL Nº 44",
        link="https://www.in.gov.br/consulta/",
        published_at="2026-07-27T06:00:00-03:00",
        collected_at="2026-07-27T14:00:00-03:00",
        edition="",
        section="",
        page=None,
        excerpt=FALSE_LDO,
        matched_terms=["concurso público", "retifica", " ldo "],
        evidence=FALSE_LDO,
    )
    kept, removed = sanitize_stored_items([item], 2027)
    assert kept == []
    assert removed == 1
