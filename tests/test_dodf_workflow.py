from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/coletar-dodf.yml"
PUBLISH_SCRIPT = ROOT / ".github/scripts/publicar_estado.sh"


def test_dodf_workflow_preserves_original_failure_without_duplication():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "continue-on-error: true" not in text
    assert "Sinalizar falha do DODF" not in text
    assert "run: python src/main_dodf.py" in text
    assert text.count("if: always()") >= 3


def test_dodf_workflow_uses_current_run_status_and_gates_invalid_notice():
    text = WORKFLOW.read_text(encoding="utf-8")

    assert text.count("RSS_RUN_ID:") >= 3
    assert "status_belongs_to_run" in text
    assert "invalid_collection" in text
    assert "if invalid:" in text
    assert "::notice title=DODF sem coleta válida::" in text
    assert "GITHUB_STEP_SUMMARY" in text


def test_publication_retry_uses_resilient_dodf_entrypoint_only_for_dodf():
    text = PUBLISH_SCRIPT.read_text(encoding="utf-8")

    assert 'if [[ "$SOURCE" == "dodf" ]]' in text
    assert "python src/main_dodf.py" in text
    # O DOU permanece no comando original, sem alteração funcional.
    assert 'python src/main.py --source "$SOURCE"' in text
