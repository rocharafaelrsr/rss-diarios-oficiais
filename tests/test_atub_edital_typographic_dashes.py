from pathlib import Path

import pytest
import yaml

from rules import ACT_MARKER_RE, Rule


ROOT = Path(__file__).resolve().parents[1]


def _atub_rule() -> Rule:
    config = yaml.safe_load((ROOT / "config/monitors.yml").read_text(encoding="utf-8"))
    data = next(rule for rule in config["rules"] if rule["id"] == "atub")
    return Rule.from_dict(data)


@pytest.mark.parametrize(
    "header",
    [
        "EDITAL DE ABERTURA - Nº 3/2027",
        "EDITAL DE ABERTURA – Nº 3/2027",
        "EDITAL DE ABERTURA — Nº 3/2027",
        "EDITAL DE ABERTURA-Nº 3/2027",
        "EDITAL DE ABERTURA–Nº 3/2027",
        "EDITAL DE ABERTURA—Nº 3/2027",
        "EDITAL DE ABERTURA —Nº 3/2027",
        "EDITAL DE ABERTURA— Nº 3/2027",
    ],
)
def test_qualified_edital_header_accepts_editorial_dashes(header: str):
    marker = ACT_MARKER_RE.match(header)
    assert marker is not None
    assert "3" in marker.group(0)


@pytest.mark.parametrize("separator", ["-", "–", "—"])
@pytest.mark.parametrize("left_space,right_space", [(" ", " "), ("", ""), (" ", ""), ("", " ")])
def test_editorial_dash_keeps_adjacent_acts_separate(
    separator: str, left_space: str, right_space: str
):
    page = (
        "PORTARIA Nº 12/2026. Designar Maria, Auditora Fiscal de Atividades Urbanas, "
        "para exercer cargo em comissão. "
        f"EDITAL DE ABERTURA{left_space}{separator}{right_space}Nº 3/2027. "
        "Torna público concurso público para o cargo de Analista."
    )
    assert _atub_rule().match("dodf", page) is None


@pytest.mark.parametrize(
    "prose",
    [
        "EDITAL DE CONVOCAÇÃO, destinado aos 50 primeiros colocados",
        "EDITAL DE RESULTADO: referente aos 30 candidatos classificados",
        "EDITAL DE RETIFICAÇÃO; alcançando os 20 candidatos remanescentes",
        "EDITAL DE CONVOCAÇÃO 50 candidatos",
        "EDITAL DE CONVOCAÇÃO no 50 candidatos",
        "EDITAL DE CONVOCAÇÃO NO 50 candidatos",
        "EDITAL DE CONVOCAÇÃO — no 50º dia",
        "EDITAL DE CONVOCAÇÃO—no 50º dia",
        "EDITAL DE CONVOCAÇÃO — NO 50º DIA",
    ],
)
def test_editorial_dash_support_does_not_reopen_prose_as_header(prose: str):
    assert ACT_MARKER_RE.search(prose) is None


def test_portuguese_no_does_not_split_valid_atub_act():
    page = (
        "PORTARIA Nº 24/2027. Convocar candidatas aprovadas no concurso público, conforme "
        "o EDITAL DE CONVOCAÇÃO — no 50º dia após a homologação, para o cargo de Auditora "
        "Fiscal de Atividades Urbanas."
    )
    assert _atub_rule().match("dodf", page) is not None


@pytest.mark.parametrize(
    "header",
    [
        "EDITAL DE ABERTURA—NO 3/2027",
        "EDITAL DE ABERTURA—N.O 3/2027",
        "EDITAL DE ABERTURA—N. O 3/2027",
        "EDITAL DE ABERTURA—N O 3/2027",
        "PORTARIA NO 2/2027",
        "PORTARIA N.O 2/2027",
        "PORTARIA N. O 2/2027",
        "PORTARIA N O 2/2027",
    ],
)
def test_uppercase_ocr_number_markers_remain_supported_with_year(header: str):
    marker = ACT_MARKER_RE.match(header)
    assert marker is not None
    assert "/2027" in marker.group(0)


@pytest.mark.parametrize("ocr_marker", ["NO", "N.O", "N. O", "N O"])
def test_ocr_portaria_keeps_adjacent_acts_separate(ocr_marker: str):
    page = (
        "EDITAL Nº 9/2026. Torna público concurso público para o cargo de Analista. "
        f"PORTARIA {ocr_marker} 2/2027. Designar João, Auditor Fiscal de Atividades Urbanas, "
        "para exercer cargo em comissão."
    )
    assert _atub_rule().match("dodf", page) is None


def test_simple_edital_still_accepts_bare_number():
    marker = ACT_MARKER_RE.match("EDITAL 3/2027")
    assert marker is not None
    assert marker.group(0).endswith("3")
