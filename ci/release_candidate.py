#!/usr/bin/env python3
"""Phase 7 release-candidate evaluation.

A release candidate is produced only when every gate in the CI pipeline is
green. This module renders a deterministic candidate manifest, marks a skip
report for the artifact store, and refuses to certify a candidate while any
required gate is missing or failed.

Gates are intentionally declared as data so the CI job and this evaluator can
never drift apart: the workflow uploads ``phase7_gates.json`` and this script
reads it.
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


def evaluate(gates: dict[str, Any]) -> dict[str, Any]:
    """Return the candidate evaluation for a gate report.

    ``gates`` uses the shape produced by the CI upload step::

        {
          "sha": "0123...",
          "workflow_run_id": 123,
          "gates": {
            "pytest-3.11": {"status": "success"},
            "pytest-3.12": {"status": "success"},
            ...
          }
        }

    A gate is ``success`` when present and green; anything else (missing,
    ``failure``, ``skipped``, ``pending``) blocks the candidate.
    """
    sha = gates.get("sha", "unknown")
    run_id = gates.get("workflow_run_id", "unknown")
    reported = gates.get("gates", {})
    missing = [gate for gate in REQUIRED_GATES if gate not in reported]
    failed = [
        gate
        for gate, state in reported.items()
        if gate in REQUIRED_GATES and state.get("status") != "success"
    ]

    green = [
        gate for gate in REQUIRED_GATES if gate not in missing and gate not in failed
    ]
    blocked = missing + failed
    ready = not blocked

    return {
        "schema": "release_candidate.v1",
        "sha": sha,
        "workflow_run_id": run_id,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "version": CANDIDATE_VERSION,
        "ready": ready,
        "required_gates": REQUIRED_GATES,
        "green_gates": green,
        "blocking_gates": blocked,
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
        print(f"  - missing/failed gate: {gate}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
