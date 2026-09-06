from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.golden_run import (
    CONTRACT_ID,
    EXPECTED_STATUS,
    acceptance_probe,
    finalize_reports,
    scenario,
)


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )


def test_scenario_is_fixed_to_one_file_and_independent_expected_behavior() -> None:
    payload = scenario()
    assert payload["contract_id"] == CONTRACT_ID
    assert payload["repository"] == "repository:demo/golden"
    assert payload["scope"] == {
        "allowed_paths": ["app.py"],
        "max_files": 1,
        "max_changed_lines": 20,
    }
    assert payload["expected_status"] == EXPECTED_STATUS
    assert len(payload["scenario_fingerprint"]) == 64


def test_acceptance_probe_observes_fixed_behavior_and_exact_scope(tmp_path: Path) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text(
        'def status():\n    return {"status": "ok"}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "add", "app.py")
    _git(
        tmp_path,
        "-c",
        "user.name=DOR Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "baseline",
    )

    app_file.write_text(
        'def status():\n    return {"status": "ok", "version": "1.0.0"}\n',
        encoding="utf-8",
    )
    result = acceptance_probe(tmp_path)

    assert result["classification"] == "ACCEPTED"
    assert result["semantic_observed"] is True
    assert result["observed_status"] == EXPECTED_STATUS
    assert result["changed_paths"] == ["app.py"]
    assert result["release_authority"] is False
    assert result["merge_authority"] is False
    assert result["deploy_authority"] is False


def test_acceptance_probe_rejects_wrong_behavior(tmp_path: Path) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text(
        'def status():\n    return {"status": "ok"}\n',
        encoding="utf-8",
    )
    _git(tmp_path, "init", "--initial-branch=main")
    _git(tmp_path, "add", "app.py")
    _git(
        tmp_path,
        "-c",
        "user.name=DOR Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "baseline",
    )

    result = acceptance_probe(tmp_path)

    assert result["classification"] == "REJECTED"
    assert result["semantic_observed"] is False


def test_finalize_requires_delivery_traceability_and_fixed_oracle() -> None:
    governed = {
        "contract_id": CONTRACT_ID,
        "classification": "GOVERNED_CHAIN_COMPLETE",
        "run_id": "a" * 64,
        "scenario": scenario(),
        "started_at": "2026-09-06T20:00:00+00:00",
        "timing": {
            "intent_to_delivery_pass_seconds": 80.0,
            "human_approval_wait_seconds": 30.0,
            "provider_proposal_seconds": 4.0,
            "prepare_seconds": 10.0,
            "apply_certificate_traceability_seconds": 40.0,
        },
        "approval": {"proposal_id": "b" * 64},
        "candidate": {
            "apply_record_id": "c" * 64,
            "candidate_id": "d" * 64,
        },
        "certification": {
            "certificate": {
                "certificate_id": "e" * 64,
                "result": "pass",
            }
        },
        "traceability": {
            "manifest": {
                "manifest_id": "f" * 64,
                "status": "complete",
            }
        },
    }
    acceptance = {
        "classification": "ACCEPTED",
        "semantic_observed": True,
        "checked_at": "2026-09-06T20:02:00+00:00",
        "authority_scope": "golden_benchmark_oracle_only",
    }

    result = finalize_reports(governed, acceptance)

    assert result["classification"] == "GOLDEN_RUN_PASS"
    assert result["metrics"]["intent_to_verified_behavior_seconds"] == 120.0
    assert result["results"]["delivery_certificate_result"] == "pass"
    assert result["results"]["traceability_status"] == "complete"
    assert len(result["evidence_id"]) == 64
    assert result["authority"]["release_authority"] is False
    assert result["authority"]["merge_authority"] is False
    assert result["authority"]["deploy_authority"] is False


def test_repository_exposes_two_phase_golden_run_without_auto_approval() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "demo-golden-prepare:" in makefile
    assert "demo-golden-apply:" in makefile
    assert 'test -n "$(PROPOSAL_ID)"' in makefile
    assert "--proposal-id \"$(PROPOSAL_ID)\"" in makefile
    assert "--yes" not in makefile

    documentation = Path("docs/GOLDEN_REAL_RUN.md").read_text(encoding="utf-8")
    assert "AWAITING_APPLY_APPROVAL" in documentation
    assert "GOLDEN_RUN_PASS" in documentation
    assert "release_authority" in documentation
    assert "/pipeline/start" in documentation
