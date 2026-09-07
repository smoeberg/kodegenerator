"""Tests for source-of-truth release gate evidence collection."""

from __future__ import annotations

from pathlib import Path

from ci.release_evidence import GATE_REQUIREMENTS, build_report, collect_until_terminal


SHA = "0123456789abcdef0123456789abcdef01234567"


def _run(run_id: int, path: str, *, sha: str = SHA) -> dict:
    return {
        "id": run_id,
        "name": path.rsplit("/", 1)[-1],
        "path": path,
        "head_sha": sha,
        "status": "completed",
        "conclusion": "success",
    }


def _check(
    check_id: int,
    name: str,
    run_id: int,
    *,
    sha: str = SHA,
    status: str = "completed",
    conclusion: str | None = "success",
) -> dict:
    return {
        "id": check_id,
        "name": name,
        "head_sha": sha,
        "status": status,
        "conclusion": conclusion,
        "completed_at": "2026-09-07T19:00:00Z" if status == "completed" else None,
        "details_url": (
            f"https://github.com/example/repo/actions/runs/{run_id}/job/{check_id}"
        ),
    }


def _all_green() -> tuple[list[dict], dict[int, dict]]:
    checks: list[dict] = []
    workflows: dict[int, dict] = {}
    seen: set[tuple[str, str]] = set()
    next_id = 100
    for requirements in GATE_REQUIREMENTS.values():
        for requirement in requirements:
            key = (requirement.workflow_path, requirement.job_name)
            if key in seen:
                continue
            seen.add(key)
            next_id += 1
            run_id = next_id + 1_000
            workflows[run_id] = _run(run_id, requirement.workflow_path)
            checks.append(_check(next_id, requirement.job_name, run_id))
    return checks, workflows


def test_all_required_gates_are_backed_by_exact_sha_provenance() -> None:
    checks, workflows = _all_green()
    report = build_report(
        sha=SHA,
        collector_workflow_run_id=42,
        check_runs=checks,
        workflow_runs=workflows,
    )

    assert report["source"] == "github_check_runs"
    assert set(report["gates"]) == set(GATE_REQUIREMENTS)
    assert {gate["status"] for gate in report["gates"].values()} == {"success"}
    for gate in report["gates"].values():
        assert len(gate["evidence"]) == gate["required_checks"]
        assert all(item["sha"] == SHA for item in gate["evidence"])
        assert all(item["run_id"] for item in gate["evidence"])
        assert all(item["check_run_id"] for item in gate["evidence"])


def test_wrong_sha_cannot_satisfy_a_gate() -> None:
    checks, workflows = _all_green()
    target = next(check for check in checks if check["name"] == "test (3.11)")
    target["head_sha"] = "f" * 40

    report = build_report(
        sha=SHA,
        collector_workflow_run_id=42,
        check_runs=checks,
        workflow_runs=workflows,
    )

    assert report["gates"]["pytest-3.11"]["status"] == "missing"


def test_wrong_workflow_path_cannot_spoof_a_named_check() -> None:
    checks, workflows = _all_green()
    target = next(check for check in checks if check["name"] == "merge-gate")
    run_id = int(target["details_url"].split("/runs/")[1].split("/")[0])
    workflows[run_id]["path"] = ".github/workflows/untrusted.yml"

    report = build_report(
        sha=SHA,
        collector_workflow_run_id=42,
        check_runs=checks,
        workflow_runs=workflows,
    )

    assert report["gates"]["merge-gate"]["status"] == "missing"


def test_sdk_proxy_gate_requires_both_matrix_checks() -> None:
    checks, workflows = _all_green()
    checks[:] = [
        check for check in checks if check["name"] != "SDK proxy matrix (exported)"
    ]

    report = build_report(
        sha=SHA,
        collector_workflow_run_id=42,
        check_runs=checks,
        workflow_runs=workflows,
    )

    assert report["gates"]["sdk-proxy"]["status"] == "missing"
    assert len(report["gates"]["sdk-proxy"]["evidence"]) == 1


def test_latest_matching_check_controls_state() -> None:
    checks, workflows = _all_green()
    old = next(check for check in checks if check["name"] == "test (3.12)")
    new_run_id = 9_999
    workflows[new_run_id] = _run(new_run_id, ".github/workflows/ci.yml")
    checks.append(
        _check(
            int(old["id"]) + 10_000,
            "test (3.12)",
            new_run_id,
            status="in_progress",
            conclusion=None,
        )
    )

    report = build_report(
        sha=SHA,
        collector_workflow_run_id=42,
        check_runs=checks,
        workflow_runs=workflows,
    )

    assert report["gates"]["pytest-3.12"]["status"] == "pending"


def test_collector_returns_immediately_on_authoritative_failure() -> None:
    checks, workflows = _all_green()
    target = next(check for check in checks if check["name"] == "merge-gate")
    target["conclusion"] = "failure"
    calls = 0

    def snapshot():
        nonlocal calls
        calls += 1
        return checks, workflows

    report = collect_until_terminal(
        sha=SHA,
        collector_workflow_run_id=42,
        snapshot=snapshot,
        timeout_seconds=30,
        poll_seconds=1,
        sleep=lambda _: None,
        monotonic=lambda: 0.0,
    )

    assert calls == 1
    assert report["gates"]["merge-gate"]["status"] == "failure"


def test_phase7_workflow_uses_collector_instead_of_synthetic_success() -> None:
    workflow = Path(".github/workflows/phase7.yml").read_text(encoding="utf-8")

    assert "python ci/release_evidence.py" in workflow
    assert "GITHUB_TOKEN: ${{ github.token }}" in workflow
    assert 'gates = {g: {"status": "success"}' not in workflow
