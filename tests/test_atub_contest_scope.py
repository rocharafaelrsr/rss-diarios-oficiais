from pathlib import Path

import pytest
import yaml

from rules import Rule


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
    ],
)
def test_atub_rule_rejects_career_mentions_without_contest_anchor(text: str):
    assert _atub_rule().match("dodf", text) is None


@pytest.mark.parametrize(
    "text",
    [
        (
            "NOMEAR os candidatos aprovados no concurso público para o cargo de Auditor "
            "Fiscal de Atividades Urbanas, observada a ordem de classificação."
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
            "Publica o resultado final do concurso para Auditor de Atividades Urbanas e a "
            "classificação dos candidatos."
        ),
        "Retificação do Edital nº 01/2022 da carreira Auditoria de Atividades Urbanas.",
    ],
)
def test_atub_rule_accepts_explicit_contest_acts(text: str):
    assert _atub_rule().match("dodf", text) is not None


def test_atub_rule_remains_dodf_only():
    text = "Concurso público para Auditor Fiscal de Atividades Urbanas."
    assert _atub_rule().match("dou", text) is None
