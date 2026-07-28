from pathlib import Path

import pytest
import yaml

from act_extraction import extract_matched_act
from presentation import MAX_EVIDENCE, strictly_relevant
from rules import ACT_MATCH_SENTINEL, Rule


ROOT = Path(__file__).resolve().parents[1]


def _atub_rule() -> Rule:
    config = yaml.safe_load((ROOT / "config/monitors.yml").read_text(encoding="utf-8"))
    data = next(rule for rule in config["rules"] if rule["id"] == "atub")
    return Rule.from_dict(data)


@pytest.mark.parametrize(
    "text",
    [
        (
            "Designar Auditora Fiscal de Atividades Urbanas para constituir comissão de "
            "sindicância. Estabelecer prazo de 30 dias para os trabalhos, podendo ser "
            "prorrogado por igual período."
        ),
        (
            "NOMEAR Geraldo para cargo de Diretor-Presidente. Em ato posterior, autoriza-se "
            "a cessão de servidor ocupante do cargo de Auditor Fiscal de Atividades Urbanas."
        ),
        (
            "EXONERAR ocupante de cargo em comissão e designar Auditor de Atividades Urbanas "
            "para responder por unidade administrativa."
        ),
        (
            "Designar João, Auditor Fiscal de Atividades Urbanas, para conduzir o certame "
            "licitatório e publicar seu resultado."
        ),
        (
            "TORNAR SEM EFEITO A NOMEAÇÃO de João, Auditor Fiscal de Atividades Urbanas, "
            "para cargo em comissão de Diretor."
        ),
    ],
)
def test_atub_rule_rejects_career_mentions_without_contest_anchor(text: str):
    assert _atub_rule().match("dodf", text) is None


def test_atub_rule_does_not_combine_adjacent_acts():
    page = (
        "EDITAL Nº 9/2026. Torna público concurso público para o cargo de Analista. "
        "PORTARIA Nº 12/2026. NOMEAR João, Auditor Fiscal de Atividades Urbanas, "
        "para exercer cargo em comissão."
    )
    assert _atub_rule().match("dodf", page) is None


@pytest.mark.parametrize(
    "qualified_header",
    [
        "EDITAL DE ABERTURA Nº 3/2027",
        "EDITAL NORMATIVO Nº 3/2027",
        "EDITAL DE CONCURSO PÚBLICO Nº 3/2027",
    ],
)
def test_qualified_edital_headers_are_act_boundaries(qualified_header: str):
    page = (
        "PORTARIA Nº 12/2026. Designar João, Auditor Fiscal de Atividades Urbanas, "
        "para exercer cargo em comissão. "
        f"{qualified_header}. Torna público concurso público para o cargo de Analista."
    )
    assert _atub_rule().match("dodf", page) is None


def test_cited_edital_remains_inside_containing_act():
    page = (
        "PORTARIA Nº 20/2027. Convocar candidatos aprovados no concurso público objeto do "
        "EDITAL Nº 3/2027 para o cargo de Auditor Fiscal de Atividades Urbanas."
    )
    matched = _atub_rule().match("dodf", page)
    assert matched is not None
    evidence = extract_matched_act(page, matched)
    assert evidence.startswith("PORTARIA Nº 20/2027")
    assert "objeto do EDITAL Nº 3/2027" in evidence


@pytest.mark.parametrize(
    "text",
    [
        (
            "NOMEAR os candidatos aprovados no concurso público para o cargo de Auditor "
            "Fiscal de Atividades Urbanas, observada a ordem de classificação."
        ),
        (
            "NOMEAR Maria, candidata aprovada e classificada, para o cargo de Auditor "
            "Fiscal de Atividades Urbanas."
        ),
        (
            "NOMEAR Ana e Beatriz, candidatas aprovadas, para o cargo de Auditor Fiscal "
            "de Atividades Urbanas."
        ),
        (
            "PRORROGAR por dois anos a validade do concurso público para Auditor Fiscal de "
            "Atividades Urbanas."
        ),
        (
            "CONVOCAR candidatos do concurso da carreira Auditoria de Atividades Urbanas "
            "para matrícula no curso de formação."
        ),
        (
            "Torna público o resultado definitivo da prova discursiva para o cargo de "
            "Auditor Fiscal de Atividades Urbanas."
        ),
        (
            "Homologa o resultado final para o cargo de Auditor Fiscal de Atividades "
            "Urbanas."
        ),
        (
            "TORNAR SEM EFEITO, em virtude de desistência expressa, a nomeação de João "
            "para o cargo de Auditor Fiscal de Atividades Urbanas."
        ),
        (
            "Reposicionar Maria para o final da lista de classificação do concurso para "
            "o cargo de Auditor Fiscal de Atividades Urbanas."
        ),
        (
            "Retifica o Edital Normativo nº 03/2027 para o cargo de Auditor Fiscal de "
            "Atividades Urbanas."
        ),
        "Retificação do Edital n.º 01/2022 da carreira Auditoria de Atividades Urbanas.",
        "Retificação do Edital nº 1/2022 da carreira Auditoria de Atividades Urbanas.",
    ],
)
def test_atub_rule_accepts_explicit_contest_acts(text: str):
    assert _atub_rule().match("dodf", text) is not None


@pytest.mark.parametrize(
    "spelling",
    [
        "Edital nº 01/2022",
        "Edital n° 01/2022",
        "Edital n.º 01/2022",
        "Edital 01/2022",
        "Edital nº 1/2022",
        "Edital n° 1/2022",
        "Edital n.º 1/2022",
        "Edital 1/2022",
    ],
)
def test_strict_relevance_accepts_all_current_edital_spellings(spelling: str):
    assert strictly_relevant("atub", "dodf", "Retificação", f"Retifica o {spelling}.", 2027)


def test_same_act_match_guides_extraction_and_cleans_internal_marker():
    page = (
        "PORTARIA Nº 10/2027. Designar João, Auditor Fiscal de Atividades Urbanas, "
        "para comissão administrativa. "
        "EDITAL N.º 03/2027. Retifica o Edital Normativo para o cargo de Auditor Fiscal "
        "de Atividades Urbanas, destinado ao provimento de vagas."
    )
    matched = _atub_rule().match("dodf", page)
    assert matched is not None
    assert matched[0].startswith(ACT_MATCH_SENTINEL)

    evidence = extract_matched_act(page, matched)

    assert evidence.startswith("EDITAL N.º 03/2027")
    assert "PORTARIA Nº 10/2027" not in evidence
    assert all(not term.startswith(ACT_MATCH_SENTINEL) for term in matched)


def test_long_selected_act_preserves_late_matched_region():
    filler = "CONSIDERANDO a necessidade administrativa e os elementos constantes do processo. " * 55
    page = (
        "PORTARIA Nº 99/2027. "
        + filler
        + "NOMEAR os candidatos aprovados no concurso público para o cargo de Auditor "
        "Fiscal de Atividades Urbanas, observada a ordem de classificação."
    )
    matched = _atub_rule().match("dodf", page)
    assert matched is not None

    evidence = extract_matched_act(page, matched)

    assert len(evidence) <= MAX_EVIDENCE + 4
    assert "candidatos aprovados no concurso público" in evidence
    assert "Auditor Fiscal de Atividades Urbanas" in evidence
    assert strictly_relevant("atub", "dodf", "PORTARIA Nº 99/2027", evidence, 2027)


def test_atub_rule_remains_dodf_only():
    text = "Concurso público para Auditor Fiscal de Atividades Urbanas."
    assert _atub_rule().match("dou", text) is None
