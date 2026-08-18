"""Enforce framework_independent layers against external package imports."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from domain.architecture_contract_v1 import ArchitectureContractV1
from services.architecture_dependency_evaluator import CheckResult, resolve_layer_id
from services.python_external_imports import collect_external_imports
from services.python_import_graph import ImportGraphError

# Default frameworks banned in framework_independent layers.
# Stdlib is always allowed; only third-party frameworks are flagged.
DEFAULT_FORBIDDEN_FRAMEWORKS = frozenset(
    {
        "fastapi",
        "flask",
        "django",
        "starlette",
        "sqlalchemy",
        "alembic",
        "celery",
        "redis",
        "boto3",
        "botocore",
        "pymongo",
        "motor",
        "httpx",
        "requests",
        "aiohttp",
        "tornado",
        "sanic",
        "litestar",
        "pydantic_settings",
    }
)


def evaluate_framework_independence(
    contract: ArchitectureContractV1,
    root: str | Path,
    *,
    forbidden_frameworks: frozenset[str] | None = None,
    result_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> tuple[CheckResult, ...]:
    """Fail when framework_independent layers import banned third-party packages."""
    independent_layers = {
        layer.id for layer in contract.layers if layer.framework_independent
    }
    if not independent_layers:
        return (
            CheckResult(
                check_id="fw-empty",
                rule_id="FW-EMPTY",
                type="framework_independence",
                severity="info",
                status="PASS",
                message="No framework_independent layers declared",
            ),
        )

    banned = forbidden_frameworks or DEFAULT_FORBIDDEN_FRAMEWORKS
    try:
        externals = collect_external_imports(root)
    except ImportGraphError as exc:
        return (
            CheckResult(
                check_id="fw-error",
                rule_id="FW-ERROR",
                type="framework_independence",
                severity="block",
                status="FAIL",
                message=f"Failed to collect external imports: {exc}",
            ),
        )

    checks: list[CheckResult] = []
    for item in externals:
        layer_id = resolve_layer_id(contract, item.source_path)
        if layer_id not in independent_layers:
            continue
        if item.module not in banned:
            continue
        checks.append(
            CheckResult(
                check_id=f"fw-{layer_id}-{item.source_path}-{item.module}",
                rule_id=f"FW-{layer_id.upper()}",
                type="framework_independence",
                severity="block",
                status="FAIL",
                message=(
                    f"framework_independent layer '{layer_id}' imports "
                    f"forbidden framework '{item.full_name}'"
                ),
                source_path=item.source_path,
            )
        )

    if not checks:
        checks.append(
            CheckResult(
                check_id="fw-ok",
                rule_id="FW-OK",
                type="framework_independence",
                severity="block",
                status="PASS",
                message=(
                    f"No forbidden framework imports in independent layers "
                    f"{sorted(independent_layers)}"
                ),
            )
        )
    return tuple(checks)
