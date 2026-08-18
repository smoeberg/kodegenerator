"""Unified Architecture Contract v1 verification over a workspace.

Combines:
1. AST import-graph dependency rule evaluation
2. AST/source constraint evaluation
3. Formal contract exceptions (fingerprint-bound, fail-closed on expiry)

Returns one aggregated verification-result shaped object for evidence adapters.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.architecture_contract_v1 import ArchitectureContractV1
from services.architecture_ast_constraint_evaluator import (
    ConstraintEvaluationError,
    evaluate_constraints,
)
from services.architecture_dependency_evaluator import (
    CheckResult,
    evaluate_dependency_rules,
)
from services.architecture_exception_policy import apply_exceptions, overall_status
from services.python_import_graph import ImportGraphError, collect_import_edges


class ArchitectureVerificationError(RuntimeError):
    """Raised when architecture verification cannot complete safely."""


@dataclass(frozen=True)
class ArchitectureVerificationResult:
    result_id: str
    contract_id: str
    contract_version: str
    contract_fingerprint: str
    status: str
    evaluated_at: datetime
    checks: tuple[CheckResult, ...]

    @property
    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.checks),
            "passed": sum(1 for c in self.checks if c.status == "PASS"),
            "failed": sum(1 for c in self.checks if c.status == "FAIL"),
            "warned": sum(1 for c in self.checks if c.status == "WARN"),
            "errored": sum(1 for c in self.checks if c.status == "ERROR"),
        }

    def to_dict(self) -> dict:
        return {
            "schema_version": "1.0",
            "result_id": self.result_id,
            "contract_id": self.contract_id,
            "contract_version": self.contract_version,
            "contract_fingerprint": self.contract_fingerprint,
            "subject": {"type": "repository_snapshot"},
            "status": self.status,
            "evaluated_at": self.evaluated_at.isoformat(),
            "evaluator": {"name": "architecture_verification", "version": "1.1"},
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
        }


def verify_architecture(
    contract: ArchitectureContractV1,
    root: str | Path,
    *,
    result_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> ArchitectureVerificationResult:
    """Run dependency-rule and constraint verification against a workspace."""
    workspace = Path(root)
    if not workspace.is_dir():
        raise ArchitectureVerificationError(f"Root must be an existing directory: {root}")

    when = evaluated_at or datetime.now(timezone.utc)
    rid = result_id or str(uuid4())

    try:
        edges = collect_import_edges(workspace)
    except ImportGraphError as exc:
        raise ArchitectureVerificationError(str(exc)) from exc

    dep_result = evaluate_dependency_rules(
        contract, edges, result_id=f"{rid}-dep", evaluated_at=when
    )

    try:
        con_result = evaluate_constraints(
            contract, workspace, result_id=f"{rid}-con", evaluated_at=when
        )
    except ConstraintEvaluationError as exc:
        raise ArchitectureVerificationError(str(exc)) from exc

    merged = tuple(dep_result.checks) + tuple(con_result.checks)
    checks = apply_exceptions(contract, merged, at=when)
    status = overall_status(checks)

    return ArchitectureVerificationResult(
        result_id=rid,
        contract_id=contract.contract_id,
        contract_version=contract.version,
        contract_fingerprint=contract.fingerprint,
        status=status,
        evaluated_at=when,
        checks=checks,
    )
