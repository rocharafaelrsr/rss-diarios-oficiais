from pathlib import Path

import pytest
import yaml

from rules import ACT_MARKER_RE, Rule


ROOT = Path(__file__).resolve().parents[1]


def _atub_rule() -> Rule:
    config = yaml.safe_load((ROOT / "config/monitors.yml").read_text(encoding="utf-8"))
    data = next(rule for rule in config["rules"] if rule["id"] == "atub")
    return Rule.from_dict(data)


@pytest.mark.parametrize("separator", ["-", "–", "—"])
def test_qualified_edital_header_accepts_editorial_dashes(separator: str):
    header = f"EDITAL DE ABERTURA {separator} Nº 3/2027"
    assert ACT_MARKER_RE.fullmatch(header) is not None


@pytest.mark.parametrize("separator", ["-", "–", "—"])
def test_editorial_dash_keeps_adjacent_acts_separate(separator: str):
    page = (
        "PORTARIA Nº 12/2026. Designar Maria, Auditora Fiscal de Atividades Urbanas, "
        "para exercer cargo em comissão. "
        f"EDITAL DE ABERTURA {separator} Nº 3/2027. Torna público concurso público "
        "para o cargo de Analista."
    )
    assert _atub_rule().match("dodf", page) is None


@pytest.mark.parametrize(
    "prose",
    [
        "EDITAL DE CONVOCAÇÃO, destinado aos 50 primeiros colocados",
        "EDITAL DE RESULTADO: referente aos 30 candidatos classificados",
        "EDITAL DE RETIFICAÇÃO; alcançando os 20 candidatos remanescentes",
    ],
)
def test_editorial_dash_support_does_not_reopen_punctuation(prose: str):
    assert ACT_MARKER_RE.search(prose) is None
