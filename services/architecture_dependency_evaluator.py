"""Evaluate import edges against Architecture Contract v1 dependency rules.

Fail-closed:
- unknown source/target layer mapping => FAIL (block)
- missing rule for a source layer that has outbound edges => FAIL (block)
- disallowed dependency => FAIL with the rule severity
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import PurePosixPath
from typing import Iterable
from uuid import uuid4

from domain.architecture_contract_v1 import ArchitectureContractV1


@dataclass(frozen=True)
class ImportEdge:
    """A directed dependency from one repo-relative path to another."""

    source_path: str
    target_path: str


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    rule_id: str
    type: str
    severity: str
    status: str
    message: str
    source_path: str | None = None
    target_path: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict:
        data = {
            "check_id": self.check_id,
            "rule_id": self.rule_id,
            "type": self.type,
            "severity": self.severity,
            "status": self.status,
            "message": self.message,
        }
        locations = []
        if self.source_path:
            loc: dict = {"path": self.source_path}
            if self.source_line is not None:
                loc["line"] = self.source_line
            locations.append(loc)
        if self.target_path:
            locations.append({"path": self.target_path})
        if locations:
            data["locations"] = locations
        return data


@dataclass(frozen=True)
class DependencyEvaluationResult:
    result_id: str
    contract_id: str
    contract_version: str
    contract_fingerprint: str
    status: str
    evaluated_at: datetime
    checks: tuple[CheckResult, ...]

    @property
    def summary(self) -> dict[str, int]:
        total = len(self.checks)
        passed = sum(1 for c in self.checks if c.status == "PASS")
        failed = sum(1 for c in self.checks if c.status == "FAIL")
        warned = sum(1 for c in self.checks if c.status == "WARN")
        errored = sum(1 for c in self.checks if c.status == "ERROR")
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "warned": warned,
            "errored": errored,
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
            "evaluator": {"name": "architecture_dependency_evaluator", "version": "1.0"},
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
        }


def normalize_repo_path(path: str) -> str:
    cleaned = path.replace("\\", "/").lstrip("./")
    pure = PurePosixPath(cleaned)
    if ".." in pure.parts:
        raise ValueError(f"path traversal not allowed: {path}")
    return pure.as_posix()


def resolve_layer_id(contract: ArchitectureContractV1, path: str) -> str | None:
    """Map a repo-relative path to the most specific matching layer id."""
    normalized = normalize_repo_path(path)
    matches: list[tuple[int, str]] = []
    for layer in contract.layers:
        pattern = layer.path
        candidates = [pattern]
        if pattern.endswith("/**"):
            prefix = pattern[:-3].rstrip("/")
            candidates.append(prefix + "/*")
            candidates.append(prefix)
        for candidate in candidates:
            if fnmatch(normalized, candidate) or (
                candidate.endswith("/*") and normalized.startswith(candidate[:-1])
            ):
                specificity = len(layer.path)
                matches.append((specificity, layer.id))
                break
            prefix = layer.path.rstrip("*").rstrip("/")
            if prefix and (normalized == prefix or normalized.startswith(prefix + "/")):
                matches.append((len(prefix), layer.id))
                break
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def evaluate_dependency_rules(
    contract: ArchitectureContractV1,
    edges: Iterable[ImportEdge],
    *,
    result_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> DependencyEvaluationResult:
    """Evaluate import edges against contract dependency_rules."""
    checks: list[CheckResult] = []
    block_failed = False

    for index, edge in enumerate(edges, start=1):
        try:
            source_path = normalize_repo_path(edge.source_path)
            target_path = normalize_repo_path(edge.target_path)
        except ValueError as exc:
            checks.append(
                CheckResult(
                    check_id=f"dep-check-{index}",
                    rule_id="DEP-PATH",
                    type="dependency_rule",
                    severity="block",
                    status="FAIL",
                    message=str(exc),
                    source_path=edge.source_path,
                    target_path=edge.target_path,
                )
            )
            block_failed = True
            continue

        source_layer = resolve_layer_id(contract, source_path)
        target_layer = resolve_layer_id(contract, target_path)

        if source_layer is None:
            checks.append(
                CheckResult(
                    check_id=f"dep-check-{index}",
                    rule_id="DEP-UNMAPPED-SOURCE",
                    type="dependency_rule",
                    severity="block",
                    status="FAIL",
                    message=f"Source path not mapped to any layer: {source_path}",
                    source_path=source_path,
                    target_path=target_path,
                )
            )
            block_failed = True
            continue

        if target_layer is None:
            checks.append(
                CheckResult(
                    check_id=f"dep-check-{index}",
                    rule_id="DEP-UNMAPPED-TARGET",
                    type="dependency_rule",
                    severity="block",
                    status="FAIL",
                    message=f"Target path not mapped to any layer: {target_path}",
                    source_path=source_path,
                    target_path=target_path,
                )
            )
            block_failed = True
            continue

        if source_layer == target_layer:
            checks.append(
                CheckResult(
                    check_id=f"dep-check-{index}",
                    rule_id="DEP-SAME-LAYER",
                    type="dependency_rule",
                    severity="info",
                    status="PASS",
                    message=f"Intra-layer dependency allowed: {source_layer}",
                    source_path=source_path,
                    target_path=target_path,
                )
            )
            continue

        rule = contract.rule_for_source(source_layer)
        if rule is None:
            checks.append(
                CheckResult(
                    check_id=f"dep-check-{index}",
                    rule_id="DEP-MISSING-RULE",
                    type="dependency_rule",
                    severity="block",
                    status="FAIL",
                    message=(
                        f"No dependency_rule defined for source layer '{source_layer}' "
                        f"({source_path} -> {target_path})"
                    ),
                    source_path=source_path,
                    target_path=target_path,
                )
            )
            block_failed = True
            continue

        if rule.allows(target_layer):
            checks.append(
                CheckResult(
                    check_id=f"dep-check-{index}",
                    rule_id=rule.id,
                    type="dependency_rule",
                    severity=rule.severity,
                    status="PASS",
                    message=f"Allowed: {source_layer} -> {target_layer}",
                    source_path=source_path,
                    target_path=target_path,
                )
            )
            continue

        status = "FAIL" if rule.severity == "block" else "WARN"
        if rule.severity == "block":
            block_failed = True
        checks.append(
            CheckResult(
                check_id=f"dep-check-{index}",
                rule_id=rule.id,
                type="dependency_rule",
                severity=rule.severity,
                status=status,
                message=(
                    f"Forbidden dependency: {source_layer} -> {target_layer} "
                    f"(allowed: {list(rule.may_depend_on) or 'none'})"
                ),
                source_path=source_path,
                target_path=target_path,
            )
        )

    if not checks:
        checks.append(
            CheckResult(
                check_id="dep-check-empty",
                rule_id="DEP-EMPTY",
                type="dependency_rule",
                severity="info",
                status="PASS",
                message="No import edges provided",
            )
        )

    overall = "FAIL" if block_failed else "PASS"
    return DependencyEvaluationResult(
        result_id=result_id or str(uuid4()),
        contract_id=contract.contract_id,
        contract_version=contract.version,
        contract_fingerprint=contract.fingerprint,
        status=overall,
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        checks=tuple(checks),
    )
