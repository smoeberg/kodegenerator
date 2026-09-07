#!/usr/bin/env python3
"""Collect authoritative GitHub check evidence for a release candidate.

The collector never invents gate results. It resolves the latest matching
GitHub check run for the exact candidate SHA and verifies the originating
workflow path before emitting provenance consumed by ``release_candidate.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CheckRequirement:
    workflow_path: str
    job_name: str


GATE_REQUIREMENTS: dict[str, tuple[CheckRequirement, ...]] = {
    "pytest-3.11": (
        CheckRequirement(".github/workflows/ci.yml", "test (3.11)"),
    ),
    "pytest-3.12": (
        CheckRequirement(".github/workflows/ci.yml", "test (3.12)"),
    ),
    "coverage-branch": (
        CheckRequirement(".github/workflows/phase7.yml", "Branch coverage gate"),
    ),
    "ruff": (
        CheckRequirement(".github/workflows/phase7.yml", "Ruff lint"),
    ),
    "bandit": (
        CheckRequirement(".github/workflows/ci.yml", "security"),
    ),
    "dep-audit": (
        CheckRequirement(".github/workflows/ci.yml", "security"),
    ),
    "alembic": (
        CheckRequirement(".github/workflows/ci.yml", "PostgreSQL migration graph"),
    ),
    "merge-gate": (
        CheckRequirement(".github/workflows/merge_gate.yml", "merge-gate"),
    ),
    "bwrap": (
        CheckRequirement(
            ".github/workflows/phase7.yml",
            "Integration runner (env-dependent suites)",
        ),
    ),
    "sdk-proxy": (
        CheckRequirement(
            ".github/workflows/phase7.yml",
            "SDK proxy matrix (stripped)",
        ),
        CheckRequirement(
            ".github/workflows/phase7.yml",
            "SDK proxy matrix (exported)",
        ),
    ),
    "e2e-integration": (
        CheckRequirement(
            ".github/workflows/phase7.yml",
            "Integration runner (env-dependent suites)",
        ),
    ),
}

_RUN_ID_RE = re.compile(r"/actions/runs/(\d+)(?:/|$)")
_TERMINAL_GATE_STATES = {"success", "failure"}


def _workflow_run_id(check: dict[str, Any]) -> int | None:
    details_url = check.get("details_url")
    if not isinstance(details_url, str):
        return None
    match = _RUN_ID_RE.search(details_url)
    return int(match.group(1)) if match else None


def _requirement_state(check: dict[str, Any]) -> str:
    if check.get("status") != "completed":
        return "pending"
    return "success" if check.get("conclusion") == "success" else "failure"


def _select_check(
    requirement: CheckRequirement,
    *,
    sha: str,
    check_runs: list[dict[str, Any]],
    workflow_runs: dict[int, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    candidates = sorted(
        (
            check
            for check in check_runs
            if check.get("name") == requirement.job_name
            and check.get("head_sha") == sha
        ),
        key=lambda check: int(check.get("id", 0)),
        reverse=True,
    )
    for check in candidates:
        run_id = _workflow_run_id(check)
        if run_id is None:
            continue
        workflow = workflow_runs.get(run_id)
        if workflow is None:
            continue
        if workflow.get("path") != requirement.workflow_path:
            continue
        if workflow.get("head_sha") != sha:
            continue
        return check, workflow
    return None


def _gate_state(states: list[str]) -> str:
    if "failure" in states:
        return "failure"
    if "missing" in states:
        return "missing"
    if "pending" in states:
        return "pending"
    return "success"


def build_report(
    *,
    sha: str,
    collector_workflow_run_id: int,
    check_runs: list[dict[str, Any]],
    workflow_runs: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    gates: dict[str, dict[str, Any]] = {}
    for gate, requirements in GATE_REQUIREMENTS.items():
        states: list[str] = []
        evidence: list[dict[str, Any]] = []
        for requirement in requirements:
            selected = _select_check(
                requirement,
                sha=sha,
                check_runs=check_runs,
                workflow_runs=workflow_runs,
            )
            if selected is None:
                states.append("missing")
                continue
            check, workflow = selected
            state = _requirement_state(check)
            states.append(state)
            evidence.append(
                {
                    "workflow": workflow.get("name"),
                    "workflow_path": workflow.get("path"),
                    "job": check.get("name"),
                    "run_id": workflow.get("id"),
                    "check_run_id": check.get("id"),
                    "sha": check.get("head_sha"),
                    "status": check.get("status"),
                    "conclusion": check.get("conclusion"),
                    "completed_at": check.get("completed_at"),
                    "details_url": check.get("details_url"),
                }
            )
        gates[gate] = {
            "status": _gate_state(states),
            "required_checks": len(requirements),
            "evidence": evidence,
        }
    return {
        "schema": "release_gate_evidence.v1",
        "source": "github_check_runs",
        "sha": sha,
        "workflow_run_id": collector_workflow_run_id,
        "gates": gates,
    }


class GitHubChecksClient:
    def __init__(self, *, repository: str, token: str, sha: str) -> None:
        if repository.count("/") != 1:
            raise ValueError("repository must use owner/name format")
        if not token.strip():
            raise ValueError("GitHub token must not be empty")
        if not sha.strip():
            raise ValueError("candidate SHA must not be empty")
        self._repository = repository
        self._token = token
        self._sha = sha

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "dor-release-evidence",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("GitHub API returned a non-object payload")
        return payload

    def snapshot(self) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
        url = (
            "https://api.github.com/repos/"
            f"{self._repository}/commits/{self._sha}/check-runs?per_page=100"
        )
        payload = self._get_json(url)
        raw_checks = payload.get("check_runs")
        if not isinstance(raw_checks, list):
            raise RuntimeError("GitHub check-runs response is missing check_runs")
        interesting_names = {
            requirement.job_name
            for requirements in GATE_REQUIREMENTS.values()
            for requirement in requirements
        }
        checks = [
            check
            for check in raw_checks
            if isinstance(check, dict)
            and check.get("name") in interesting_names
            and check.get("head_sha") == self._sha
        ]
        run_ids = {
            run_id
            for check in checks
            if (run_id := _workflow_run_id(check)) is not None
        }
        workflows: dict[int, dict[str, Any]] = {}
        for run_id in sorted(run_ids):
            run = self._get_json(
                f"https://api.github.com/repos/{self._repository}/actions/runs/{run_id}"
            )
            workflows[run_id] = run
        return checks, workflows


def collect_until_terminal(
    *,
    sha: str,
    collector_workflow_run_id: int,
    snapshot: Callable[
        [], tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]
    ],
    timeout_seconds: int,
    poll_seconds: int,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if timeout_seconds < 0 or poll_seconds < 1:
        raise ValueError("timeout_seconds must be non-negative and poll_seconds positive")
    deadline = monotonic() + timeout_seconds
    while True:
        checks, workflows = snapshot()
        report = build_report(
            sha=sha,
            collector_workflow_run_id=collector_workflow_run_id,
            check_runs=checks,
            workflow_runs=workflows,
        )
        states = {gate["status"] for gate in report["gates"].values()}
        if states <= _TERMINAL_GATE_STATES or "failure" in states:
            return report
        now = monotonic()
        if now >= deadline:
            return report
        sleep(min(float(poll_seconds), max(0.0, deadline - now)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.getenv("GITHUB_REPOSITORY"))
    parser.add_argument("--sha", default=os.getenv("GITHUB_SHA"))
    parser.add_argument(
        "--workflow-run-id",
        type=int,
        default=int(os.getenv("GITHUB_RUN_ID", "0")),
    )
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    parser.add_argument("--output", default="phase7_gates.json")
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--poll-seconds", type=int, default=10)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.repository or not args.sha or not args.token or args.workflow_run_id < 1:
        raise SystemExit(
            "repository, sha, workflow-run-id and GitHub token are required"
        )
    client = GitHubChecksClient(
        repository=args.repository,
        token=args.token,
        sha=args.sha,
    )
    report = collect_until_terminal(
        sha=args.sha,
        collector_workflow_run_id=args.workflow_run_id,
        snapshot=client.snapshot,
        timeout_seconds=args.timeout_seconds,
        poll_seconds=args.poll_seconds,
    )
    output = Path(args.output)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(output.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
