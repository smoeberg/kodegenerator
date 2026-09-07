#!/usr/bin/env python3
"""Phase 7 release-candidate evaluation.

A release candidate is produced only when every required gate is backed by
completed, successful, exact-SHA GitHub check evidence. Missing, failed,
pending, or provenance-incomplete gates block certification.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CANDIDATE_VERSION = "1"
REQUIRED_GATES: list[str] = [
    "pytest-3.11",
    "pytest-3.12",
    "coverage-branch",
    "ruff",
    "bandit",
    "dep-audit",
    "alembic",
    "merge-gate",
    "bwrap",
    "sdk-proxy",
    "e2e-integration",
]


def _valid_gate_evidence(gate: Any, *, sha: str) -> bool:
    if not isinstance(gate, dict) or gate.get("status") != "success":
        return False
    required_checks = gate.get("required_checks")
    evidence = gate.get("evidence")
    if type(required_checks) is not int or required_checks < 1:
        return False
    if not isinstance(evidence, list) or len(evidence) != required_checks:
        return False
    for item in evidence:
        if not isinstance(item, dict):
            return False
        if item.get("sha") != sha:
            return False
        if item.get("status") != "completed" or item.get("conclusion") != "success":
            return False
        if not isinstance(item.get("workflow"), str) or not item["workflow"].strip():
            return False
        workflow_path = item.get("workflow_path")
        if not isinstance(workflow_path, str) or not workflow_path.startswith(
            ".github/workflows/"
        ):
            return False
        if not isinstance(item.get("job"), str) or not item["job"].strip():
            return False
        if type(item.get("run_id")) is not int or item["run_id"] < 1:
            return False
        if type(item.get("check_run_id")) is not int or item["check_run_id"] < 1:
            return False
        if not isinstance(item.get("completed_at"), str) or not item[
            "completed_at"
        ].strip():
            return False
    return True


def evaluate(gates: dict[str, Any]) -> dict[str, Any]:
    """Return a fail-closed candidate evaluation for authoritative gate evidence."""
    sha = gates.get("sha", "unknown")
    run_id = gates.get("workflow_run_id", "unknown")
    reported = gates.get("gates", {})
    evidence_envelope_valid = (
        gates.get("schema") == "release_gate_evidence.v1"
        and gates.get("source") == "github_check_runs"
        and isinstance(sha, str)
        and len(sha) == 40
        and isinstance(reported, dict)
    )
    if not evidence_envelope_valid:
        reported = reported if isinstance(reported, dict) else {}

    missing = [gate for gate in REQUIRED_GATES if gate not in reported]
    failed: list[str] = []
    invalid_provenance: list[str] = []
    for gate in REQUIRED_GATES:
        if gate not in reported:
            continue
        state = reported[gate]
        if not isinstance(state, dict) or state.get("status") != "success":
            failed.append(gate)
            continue
        if not evidence_envelope_valid or not _valid_gate_evidence(state, sha=sha):
            invalid_provenance.append(gate)

    blocked = list(dict.fromkeys(missing + failed + invalid_provenance))
    green = [gate for gate in REQUIRED_GATES if gate not in blocked]
    ready = not blocked and evidence_envelope_valid

    return {
        "schema": "release_candidate.v1",
        "sha": sha,
        "workflow_run_id": run_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "version": CANDIDATE_VERSION,
        "ready": ready,
        "evidence_source": gates.get("source"),
        "required_gates": REQUIRED_GATES,
        "green_gates": green,
        "blocking_gates": blocked,
        "invalid_provenance_gates": invalid_provenance,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: release_candidate.py <gates.json> [candidate.json]", file=sys.stderr
        )
        return 2
    gates_path = Path(argv[0])
    out_path = Path(argv[1]) if len(argv) > 1 else Path("release_candidate.json")

    try:
        gates = json.loads(gates_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::error::cannot read gates report {gates_path}: {exc}")
        return 1

    candidate = evaluate(gates)
    out_path.write_text(json.dumps(candidate, indent=2), encoding="utf-8")

    if candidate["ready"]:
        print(f"::notice::release candidate READY for {candidate['sha']}")
        print(f"Release candidate written to {out_path}")
        return 0
    print(f"::error::release candidate BLOCKED for {candidate['sha']}")
    for gate in candidate["blocking_gates"]:
        print(f"  - missing/failed/unverified gate: {gate}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
