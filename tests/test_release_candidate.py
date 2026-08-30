"""Unit tests for the Phase 7 release-candidate evaluator."""

from __future__ import annotations

from ci.release_candidate import REQUIRED_GATES, evaluate


def _gates(**states: str) -> dict:
    report = {
        "sha": "0123456789abcdef0123456789abcdef01234567",
        "workflow_run_id": 42,
        "gates": {gate: {"status": "success"} for gate in REQUIRED_GATES},
    }
    # kwargs cannot carry dots/hyphens, so map friendly names to gate ids
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
        report["gates"][gate] = {"status": status}
    return report


def test_all_green_produces_ready_candidate() -> None:
    candidate = evaluate(_gates())
    assert candidate["ready"] is True
    assert candidate["blocking_gates"] == []
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
    report["gates"]["some-unknown-gate"] = {"status": "failure"}
    assert evaluate(report)["ready"] is True


def test_candidate_contains_sha_and_schema() -> None:
    candidate = evaluate(_gates())
    assert candidate["sha"].startswith("01234567")
    assert candidate["schema"] == "release_candidate.v1"
