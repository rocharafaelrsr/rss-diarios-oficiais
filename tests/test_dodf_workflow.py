from pathlib import Path


WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/coletar-dodf.yml"


def test_dodf_workflow_preserves_original_failure_without_duplication():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "continue-on-error: true" not in text
    assert "Sinalizar falha do DODF" not in text
    assert "run: python src/main_dodf.py" in text
    assert text.count("if: always()") >= 3


def test_dodf_workflow_writes_non_failing_diagnostic_summary():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "Resumir diagnóstico do DODF" in text
    assert "::notice title=DODF sem coleta válida::" in text
    assert "GITHUB_STEP_SUMMARY" in text
