"""Apply formal architecture exceptions to evaluation checks (fail-closed)."""
from __future__ import annotations

from datetime import datetime, timezone

from domain.architecture_contract_v1 import ArchitectureContractV1
from domain.architecture_exceptions import ExceptionV1, find_active_exception
from services.architecture_dependency_evaluator import CheckResult


def apply_exceptions(
    contract: ArchitectureContractV1,
    checks: tuple[CheckResult, ...] | list[CheckResult],
    *,
    at: datetime | None = None,
) -> tuple[CheckResult, ...]:
    """Suppress FAIL/WARN checks covered by an active contract exception.

    Expired exceptions never suppress. Suppression is recorded as PASS with an
    explicit message referencing the exception id (audit trail).
    """
    when = at or datetime.now(timezone.utc)
    exceptions: tuple[ExceptionV1, ...] = getattr(contract, "exceptions", ()) or ()
    if not exceptions:
        return tuple(checks)

    adjusted: list[CheckResult] = []
    for check in checks:
        if check.status not in {"FAIL", "WARN"}:
            adjusted.append(check)
            continue

        path = check.source_path
        exc = find_active_exception(
            exceptions, rule_id=check.rule_id, path=path, at=when
        )
        if exc is None and path is not None:
            exc = find_active_exception(
                exceptions,
                rule_id=check.rule_id,
                path=check.target_path,
                at=when,
            )
        if exc is None:
            adjusted.append(check)
            continue

        adjusted.append(
            CheckResult(
                check_id=check.check_id,
                rule_id=check.rule_id,
                type=check.type,
                severity=check.severity,
                status="PASS",
                message=(
                    f"Suppressed by {exc.id} ({exc.reason}; approved_by={exc.approved_by})"
                ),
                source_path=check.source_path,
                target_path=check.target_path,
                source_line=check.source_line,
            )
        )
    return tuple(adjusted)


def overall_status(checks: tuple[CheckResult, ...]) -> str:
    if any(c.status == "FAIL" and c.severity == "block" for c in checks):
        return "FAIL"
    if any(c.status == "FAIL" for c in checks):
        return "FAIL"
    return "PASS"
