"""Graph-based architecture constraints using import edges and external imports.

- max_module_fanout: limit unique outbound internal dependencies per source file
- allowlisted_dependencies_only: only approved third-party top-level packages
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from domain.architecture_contract_v1 import ConstraintV1
from services.architecture_dependency_evaluator import CheckResult, ImportEdge
from services.python_external_imports import ExternalImport, collect_external_imports
from services.python_import_graph import ImportGraphError, collect_import_edges


def _status_for_severity(severity: str, violated: bool) -> str:
    if not violated:
        return "PASS"
    if severity == "block":
        return "FAIL"
    if severity == "warn":
        return "WARN"
    return "PASS"


def _path_in_scope(path: str, scope: tuple[str, ...]) -> bool:
    from fnmatch import fnmatch

    if not scope:
        return True
    for pattern in scope:
        candidates = [pattern]
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            candidates.extend([prefix + "/*", prefix])
        for candidate in candidates:
            if fnmatch(path, candidate):
                return True
            prefix = candidate.rstrip("*").rstrip("/")
            if prefix and (path == prefix or path.startswith(prefix + "/")):
                return True
    return False


def evaluate_max_module_fanout(
    constraint: ConstraintV1,
    edges: list[ImportEdge],
) -> list[CheckResult]:
    params = dict(constraint.params or {})
    max_raw = params.get("max_fanout", params.get("max"))
    if not isinstance(max_raw, int) or max_raw < 0:
        return [
            CheckResult(
                check_id=f"con-{constraint.id}-config",
                rule_id=constraint.id,
                type="constraint",
                severity="block",
                status="FAIL",
                message=(
                    f"{constraint.id} max_module_fanout requires params.max_fanout "
                    f"as a non-negative integer"
                ),
            )
        ]

    outbound: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if not _path_in_scope(edge.source_path, constraint.scope):
            continue
        outbound[edge.source_path].add(edge.target_path)

    checks: list[CheckResult] = []
    for source, targets in sorted(outbound.items()):
        fanout = len(targets)
        violated = fanout > max_raw
        status = _status_for_severity(constraint.severity, violated)
        if violated:
            checks.append(
                CheckResult(
                    check_id=f"con-{constraint.id}-{source}",
                    rule_id=constraint.id,
                    type="constraint",
                    severity=constraint.severity,
                    status=status,
                    message=(
                        f"Module fanout {fanout} exceeds max_fanout={max_raw} "
                        f"in {source} ({fanout} unique internal imports)"
                    ),
                    source_path=source,
                )
            )

    if not checks:
        scanned = sum(
            1
            for edge in edges
            if _path_in_scope(edge.source_path, constraint.scope)
        )
        # Count unique source files in scope with any edge, plus pass message
        sources_in_scope = {
            e.source_path for e in edges if _path_in_scope(e.source_path, constraint.scope)
        }
        checks.append(
            CheckResult(
                check_id=f"con-{constraint.id}",
                rule_id=constraint.id,
                type="constraint",
                severity=constraint.severity,
                status="PASS",
                message=(
                    f"All modules within max_fanout={max_raw} "
                    f"({len(sources_in_scope)} source files with edges in scope)"
                ),
            )
        )
    return checks


def evaluate_allowlisted_dependencies(
    constraint: ConstraintV1,
    externals: list[ExternalImport],
) -> list[CheckResult]:
    params: Mapping[str, Any] = constraint.params or {}
    allow_raw = params.get("allowlist") or params.get("allowed") or []
    if not isinstance(allow_raw, list):
        return [
            CheckResult(
                check_id=f"con-{constraint.id}-config",
                rule_id=constraint.id,
                type="constraint",
                severity="block",
                status="FAIL",
                message=(
                    f"{constraint.id} allowlisted_dependencies_only requires "
                    f"params.allowlist as a list of package names"
                ),
            )
        ]

    allowlist = {str(item).split(".")[0] for item in allow_raw if str(item).strip()}
    checks: list[CheckResult] = []

    for item in externals:
        if not _path_in_scope(item.source_path, constraint.scope):
            continue
        if item.module in allowlist:
            continue
        status = _status_for_severity(constraint.severity, True)
        checks.append(
            CheckResult(
                check_id=f"con-{constraint.id}-{item.source_path}-{item.module}",
                rule_id=constraint.id,
                type="constraint",
                severity=constraint.severity,
                status=status,
                message=(
                    f"Non-allowlisted dependency '{item.full_name}' "
                    f"imported in {item.source_path} "
                    f"(allowlist: {sorted(allowlist) or 'empty'})"
                ),
                source_path=item.source_path,
            )
        )

    if not checks:
        checks.append(
            CheckResult(
                check_id=f"con-{constraint.id}",
                rule_id=constraint.id,
                type="constraint",
                severity=constraint.severity,
                status="PASS",
                message=(
                    f"All external dependencies within allowlist "
                    f"({sorted(allowlist) or 'empty'})"
                ),
            )
        )
    return checks


def load_edges(root: Path) -> list[ImportEdge]:
    try:
        return collect_import_edges(root)
    except ImportGraphError as exc:
        raise ValueError(str(exc)) from exc


def load_externals(root: Path) -> list[ExternalImport]:
    try:
        return collect_external_imports(root)
    except ImportGraphError as exc:
        raise ValueError(str(exc)) from exc
