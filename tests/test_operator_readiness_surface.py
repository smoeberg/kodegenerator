from pathlib import Path

from scripts.operator_readiness import check_build_context


def test_repository_dockerignore_excludes_local_env_secrets() -> None:
    result = check_build_context(Path(".dockerignore"))

    assert result.status == "PASS"


def test_makefile_exposes_operator_readiness_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "operator-readiness:" in makefile
    assert "python3 scripts/operator_readiness.py" in makefile


def test_operator_readiness_runbook_preserves_existing_recovery_authority() -> None:
    runbook = Path("docs/OPERATOR_READINESS.md").read_text(encoding="utf-8")
    normalized = " ".join(runbook.split())

    assert "does not replace staging certification, rollback" in normalized
    assert "real restore into a fresh target" in normalized
    assert "READY` report is post-deploy evidence, not release authority" in normalized
