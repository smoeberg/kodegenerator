"""Unit tests for the Phase 7 release-candidate evaluator."""

from __future__ import annotations

from ci.release_candidate import evaluate, REQUIRED_GATES


SHA = "0123456789abcdef0123456789abcdef01234567"


def _gate(gate: str, *, status: str = "success", sha: str = SHA) -> dict:
    return {
        "status": status,
        "required_checks": 1,
        "evidence": [
            {
                "workflow": "DOR CI",
                "workflow_path": ".github/workflows/ci.yml",
                "job": gate,
                "run_id": 100,
                "check_run_id": 200,
                "sha": sha,
                "status": "completed",
                "conclusion": "success" if status == "success" else "failure",
                "completed_at": "2026-09-07T19:00:00Z",
                "details_url": "https://github.com/example/repo/actions/runs/100/job/200",
            }
        ],
    }


def _gates(**states: str) -> dict:
    report = {
        "schema": "release_gate_evidence.v1",
        "source": "github_check_runs",
        "sha": SHA,
        "workflow_run_id": 42,
        "gates": {gate: _gate(gate) for gate in REQUIRED_GATES},
    }
    name_to_gate = {
        "pytest_3_11": "pytest-3.11",
        "pytest_3_12": "pytest-3.12",
        "coverage_branch": "coverage-branch",
        "dep_audit": "dep-audit",
        "merge_gate": "merge-gate",
        "sdk_proxy": "sdk-proxy",
        "e2e_integration": "e2e-integration",
    }
    for name, status in states.items():
        gate = name_to_gate.get(name, name)
        if gate not in REQUIRED_GATES:
            raise KeyError(f"{name!r} does not resolve to a known gate")
        report["gates"][gate] = _gate(gate, status=status)
    return report


def test_all_green_produces_ready_candidate() -> None:
    candidate = evaluate(_gates())
    assert candidate["ready"] is True
    assert candidate["blocking_gates"] == []
    assert candidate["invalid_provenance_gates"] == []
    assert set(candidate["green_gates"]) == set(REQUIRED_GATES)


def test_single_failed_gate_blocks() -> None:
    candidate = evaluate(_gates(pytest_3_11="failure"))
    assert candidate["ready"] is False
    assert "pytest-3.11" in candidate["blocking_gates"]


def test_missing_gate_blocks() -> None:
    report = _gates()
    del report["gates"]["ruff"]
    candidate = evaluate(report)
    assert candidate["ready"] is False
    assert "ruff" in candidate["blocking_gates"]


def test_unknown_extra_gates_are_ignored() -> None:
    report = _gates()
    report["gates"]["some-unknown-gate"] = _gate(
        "some-unknown-gate", status="failure"
    )
    assert evaluate(report)["ready"] is True


def test_candidate_contains_sha_and_schema() -> None:
    candidate = evaluate(_gates())
    assert candidate["sha"] == SHA
    assert candidate["schema"] == "release_candidate.v1"
    assert candidate["evidence_source"] == "github_check_runs"


def test_synthetic_success_without_provenance_is_rejected() -> None:
    report = _gates()
    report["gates"]["ruff"] = {"status": "success"}

    candidate = evaluate(report)

    assert candidate["ready"] is False
    assert "ruff" in candidate["invalid_provenance_gates"]


def test_wrong_sha_provenance_is_rejected() -> None:
    report = _gates()
    report["gates"]["merge-gate"] = _gate("merge-gate", sha="f" * 40)

    candidate = evaluate(report)

    assert candidate["ready"] is False
    assert "merge-gate" in candidate["invalid_provenance_gates"]


def test_non_authoritative_evidence_envelope_is_rejected() -> None:
    report = _gates()
    report["source"] = "synthetic"

    candidate = evaluate(report)

    assert candidate["ready"] is False
    assert set(candidate["invalid_provenance_gates"]) == set(REQUIRED_GATES)
