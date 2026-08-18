"""AST- and source-based evaluation of Architecture Contract v1 constraints.

Supported constraint types (v1):
- forbid_pattern / require_pattern: token-prepared regex with match_mode + line numbers
- forbid_call: structured AST Call matching
- no_path_traversal_writes: AST write/open with '..' (literal + L1 local flow)
- max_module_fanout: unique outbound internal imports per source file
- allowlisted_dependencies_only: third-party packages must be on allowlist

Unsupported constraint types with severity=block fail closed.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
import re
from typing import Any, Iterable
from uuid import uuid4

from domain.architecture_contract_v1 import ArchitectureContractV1, ConstraintV1
from services.architecture_ast_call_matcher import find_forbidden_calls
from services.architecture_ast_source import (
    MatchMode,
    line_number_at,
    prepare_pattern_source,
)
from services.architecture_dependency_evaluator import CheckResult, normalize_repo_path
from services.architecture_graph_constraints import (
    evaluate_allowlisted_dependencies,
    evaluate_max_module_fanout,
    load_edges,
    load_externals,
)


class ConstraintEvaluationError(ValueError):
    """Raised when constraint evaluation cannot complete safely."""


_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "node_modules",
        "dist",
        "build",
        ".tox",
    }
)

_SUPPORTED = frozenset(
    {
        "forbid_pattern",
        "require_pattern",
        "forbid_call",
        "no_path_traversal_writes",
        "max_module_fanout",
        "allowlisted_dependencies_only",
    }
)


@dataclass(frozen=True)
class ConstraintEvaluationResult:
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
            "evaluator": {"name": "architecture_ast_constraint_evaluator", "version": "1.5"},
            "checks": [c.to_dict() for c in self.checks],
            "summary": self.summary,
        }


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        if path.is_file():
            yield path


def _repo_relative(root: Path, path: Path) -> str:
    return normalize_repo_path(path.resolve().relative_to(root.resolve()).as_posix())


def _path_in_scope(path: str, scope: tuple[str, ...]) -> bool:
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


def _compile_pattern(constraint: ConstraintV1) -> re.Pattern[str]:
    if not constraint.pattern:
        raise ConstraintEvaluationError(f"{constraint.id} requires a pattern")
    try:
        return re.compile(constraint.pattern)
    except re.error as exc:
        raise ConstraintEvaluationError(
            f"Invalid regex in {constraint.id}: {exc}"
        ) from exc


def _match_mode(constraint: ConstraintV1) -> MatchMode:
    raw = (constraint.params or {}).get("match_mode", "include_strings")
    if raw == "code_only":
        return "code_only"
    return "include_strings"


def _status_for_severity(severity: str, violated: bool) -> str:
    if not violated:
        return "PASS"
    if severity == "block":
        return "FAIL"
    if severity == "warn":
        return "WARN"
    return "PASS"


def _string_has_path_traversal(value: str) -> bool:
    try:
        pure = PurePosixPath(value.replace("\\", "/"))
    except Exception:
        return ".." in value
    return ".." in pure.parts or "../" in value or "..\\" in value


def _contains_path_traversal_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return _string_has_path_traversal(node.value)
    return False


def _arg_has_path_traversal(arg: ast.AST, env: dict[str, str]) -> bool:
    """True if arg embeds '..' as a string literal or L1-resolved Name."""
    if _contains_path_traversal_literal(arg):
        return True
    if isinstance(arg, ast.Name) and arg.id in env:
        return _string_has_path_traversal(env[arg.id])
    for child in ast.walk(arg):
        if child is arg:
            continue
        if _contains_path_traversal_literal(child):
            return True
        if isinstance(child, ast.Name) and child.id in env:
            if _string_has_path_traversal(env[child.id]):
                return True
    return False


def _is_write_open_call(node: ast.Call) -> bool:
    func = node.func
    name = None
    if isinstance(func, ast.Name):
        name = func.id
    elif isinstance(func, ast.Attribute):
        name = func.attr

    if name in {"write_text", "write_bytes", "writelines", "write"}:
        return True
    if name == "open":
        for keyword in node.keywords:
            if keyword.arg in {"mode", None} and isinstance(keyword.value, ast.Constant):
                mode = str(keyword.value.value)
                if any(flag in mode for flag in ("w", "a", "x", "+")):
                    return True
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
            if any(flag in mode for flag in ("w", "a", "x", "+")):
                return True
    return False


class _PathTraversalWriteVisitor(ast.NodeVisitor):
    """L0 literals + L1 local Name=string flow within each function/class scope."""

    def __init__(self) -> None:
        self.hits: list[tuple[int, str]] = []
        self._env_stack: list[dict[str, str]] = [{}]

    @property
    def env(self) -> dict[str, str]:
        return self._env_stack[-1]

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._env_stack.append({})
        self.generic_visit(node)
        self._env_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._env_stack.append({})
        self.generic_visit(node)
        self._env_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._env_stack.append({})
        self.generic_visit(node)
        self._env_stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.env[target.id] = node.value.value
        else:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    self.env.pop(target.id, None)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
        if isinstance(node.target, ast.Name):
            if (
                node.value is not None
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                self.env[node.target.id] = node.value.value
            elif node.value is not None:
                self.env.pop(node.target.id, None)

    def visit_Call(self, node: ast.Call) -> None:
        self.generic_visit(node)
        if not _is_write_open_call(node):
            return
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            if _arg_has_path_traversal(arg, self.env):
                line = getattr(node, "lineno", 1)
                self.hits.append(
                    (line, "write/open call embeds path traversal ('..')")
                )
                break


def _find_path_traversal_writes(source: str, filename: str) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ConstraintEvaluationError(f"Syntax error in {filename}: {exc}") from exc

    visitor = _PathTraversalWriteVisitor()
    visitor.visit(tree)
    return visitor.hits


def _forbid_call_params(constraint: ConstraintV1) -> tuple[str, dict[str, Any]]:
    params = dict(constraint.params or {})
    callee = params.get("callee")
    if not isinstance(callee, str) or not callee.strip():
        raise ConstraintEvaluationError(
            f"{constraint.id} forbid_call requires params.callee"
        )
    keywords = params.get("keywords") or {}
    if not isinstance(keywords, dict):
        raise ConstraintEvaluationError(
            f"{constraint.id} forbid_call params.keywords must be an object"
        )
    return callee.strip(), dict(keywords)


def evaluate_constraints(
    contract: ArchitectureContractV1,
    root: str | Path,
    *,
    result_id: str | None = None,
    evaluated_at: datetime | None = None,
) -> ConstraintEvaluationResult:
    workspace = Path(root)
    if not workspace.is_dir():
        raise ConstraintEvaluationError(f"Root must be an existing directory: {root}")

    checks: list[CheckResult] = []
    block_failed = False
    files = list(_iter_python_files(workspace))

    # Lazy-loaded graph data for graph constraints
    edges_cache: list | None = None
    externals_cache: list | None = None

    def edges():
        nonlocal edges_cache
        if edges_cache is None:
            try:
                edges_cache = load_edges(workspace)
            except ValueError as exc:
                raise ConstraintEvaluationError(str(exc)) from exc
        return edges_cache

    def externals():
        nonlocal externals_cache
        if externals_cache is None:
            try:
                externals_cache = load_externals(workspace)
            except ValueError as exc:
                raise ConstraintEvaluationError(str(exc)) from exc
        return externals_cache

    if not contract.constraints:
        checks.append(
            CheckResult(
                check_id="con-empty",
                rule_id="CON-EMPTY",
                type="constraint",
                severity="info",
                status="PASS",
                message="No constraints defined on architecture contract",
            )
        )
    else:
        for constraint in contract.constraints:
            if constraint.type not in _SUPPORTED:
                if constraint.severity == "block":
                    checks.append(
                        CheckResult(
                            check_id=f"con-{constraint.id}",
                            rule_id=constraint.id,
                            type="constraint",
                            severity=constraint.severity,
                            status="FAIL",
                            message=(
                                f"Unsupported constraint type '{constraint.type}' "
                                f"with severity=block (fail-closed)"
                            ),
                        )
                    )
                    block_failed = True
                else:
                    checks.append(
                        CheckResult(
                            check_id=f"con-{constraint.id}",
                            rule_id=constraint.id,
                            type="constraint",
                            severity=constraint.severity,
                            status="SKIPPED",
                            message=f"Unsupported constraint type '{constraint.type}' skipped",
                        )
                    )
                continue

            scoped = [
                path
                for path in files
                if _path_in_scope(_repo_relative(workspace, path), constraint.scope)
            ]

            if constraint.type == "forbid_pattern":
                regex = _compile_pattern(constraint)
                mode = _match_mode(constraint)
                violations: list[CheckResult] = []
                for path in scoped:
                    rel = _repo_relative(workspace, path)
                    original = path.read_text(encoding="utf-8")
                    prepared = prepare_pattern_source(original, match_mode=mode)
                    match = regex.search(prepared)
                    if match:
                        line = line_number_at(original, match.start())
                        status = _status_for_severity(constraint.severity, True)
                        if status == "FAIL":
                            block_failed = True
                        violations.append(
                            CheckResult(
                                check_id=f"con-{constraint.id}-{rel}-{line}",
                                rule_id=constraint.id,
                                type="constraint",
                                severity=constraint.severity,
                                status=status,
                                message=(
                                    f"Forbidden pattern matched in {rel}:line {line}: "
                                    f"/{constraint.pattern}/"
                                ),
                                source_path=rel,
                                source_line=line,
                            )
                        )
                if violations:
                    checks.extend(violations)
                else:
                    checks.append(
                        CheckResult(
                            check_id=f"con-{constraint.id}",
                            rule_id=constraint.id,
                            type="constraint",
                            severity=constraint.severity,
                            status="PASS",
                            message=(
                                f"Forbidden pattern not found in scope "
                                f"({len(scoped)} files, match_mode={mode}): "
                                f"/{constraint.pattern}/"
                            ),
                        )
                    )

            elif constraint.type == "require_pattern":
                regex = _compile_pattern(constraint)
                mode = _match_mode(constraint)
                found = False
                found_line: int | None = None
                found_path: str | None = None
                for path in scoped:
                    rel = _repo_relative(workspace, path)
                    original = path.read_text(encoding="utf-8")
                    prepared = prepare_pattern_source(original, match_mode=mode)
                    match = regex.search(prepared)
                    if match:
                        found = True
                        found_line = line_number_at(original, match.start())
                        found_path = rel
                        break
                status = _status_for_severity(constraint.severity, not found)
                if status == "FAIL":
                    block_failed = True
                if found:
                    message = (
                        f"Required pattern found in {found_path}:line {found_line} "
                        f"({len(scoped)} files scanned, match_mode={mode})"
                    )
                else:
                    message = (
                        f"Required pattern missing in scope "
                        f"({len(scoped)} files, match_mode={mode}): /{constraint.pattern}/"
                    )
                checks.append(
                    CheckResult(
                        check_id=f"con-{constraint.id}",
                        rule_id=constraint.id,
                        type="constraint",
                        severity=constraint.severity,
                        status=status,
                        message=message,
                        source_path=found_path,
                        source_line=found_line,
                    )
                )

            elif constraint.type == "forbid_call":
                callee, keywords = _forbid_call_params(constraint)
                violations = []
                for path in scoped:
                    rel = _repo_relative(workspace, path)
                    text = path.read_text(encoding="utf-8")
                    for match in find_forbidden_calls(
                        text, path=rel, callee=callee, keywords=keywords
                    ):
                        status = _status_for_severity(constraint.severity, True)
                        if status == "FAIL":
                            block_failed = True
                        violations.append(
                            CheckResult(
                                check_id=f"con-{constraint.id}-{rel}-{match.line}",
                                rule_id=constraint.id,
                                type="constraint",
                                severity=constraint.severity,
                                status=status,
                                message=match.message,
                                source_path=rel,
                                source_line=match.line,
                            )
                        )
                if violations:
                    checks.extend(violations)
                else:
                    checks.append(
                        CheckResult(
                            check_id=f"con-{constraint.id}",
                            rule_id=constraint.id,
                            type="constraint",
                            severity=constraint.severity,
                            status="PASS",
                            message=(
                                f"Forbidden call '{callee}' not found in scope "
                                f"({len(scoped)} files)"
                            ),
                        )
                    )

            elif constraint.type == "no_path_traversal_writes":
                violations = []
                for path in scoped:
                    rel = _repo_relative(workspace, path)
                    text = path.read_text(encoding="utf-8")
                    for line, message in _find_path_traversal_writes(text, rel):
                        status = _status_for_severity(constraint.severity, True)
                        if status == "FAIL":
                            block_failed = True
                        violations.append(
                            CheckResult(
                                check_id=f"con-{constraint.id}-{rel}-{line}",
                                rule_id=constraint.id,
                                type="constraint",
                                severity=constraint.severity,
                                status=status,
                                message=f"{message} at {rel}:{line}",
                                source_path=rel,
                                source_line=line,
                            )
                        )
                if violations:
                    checks.extend(violations)
                else:
                    checks.append(
                        CheckResult(
                            check_id=f"con-{constraint.id}",
                            rule_id=constraint.id,
                            type="constraint",
                            severity=constraint.severity,
                            status="PASS",
                            message=(
                                f"No path-traversal writes detected in scope "
                                f"({len(scoped)} files)"
                            ),
                        )
                    )

            elif constraint.type == "max_module_fanout":
                fanout_checks = evaluate_max_module_fanout(constraint, edges())
                for c in fanout_checks:
                    if c.status == "FAIL" and constraint.severity == "block":
                        block_failed = True
                    elif c.status == "FAIL":
                        block_failed = block_failed or c.severity == "block"
                checks.extend(fanout_checks)

            elif constraint.type == "allowlisted_dependencies_only":
                allow_checks = evaluate_allowlisted_dependencies(constraint, externals())
                for c in allow_checks:
                    if c.status == "FAIL" and (
                        constraint.severity == "block" or c.severity == "block"
                    ):
                        block_failed = True
                checks.extend(allow_checks)

    overall = "FAIL" if block_failed else "PASS"
    return ConstraintEvaluationResult(
        result_id=result_id or str(uuid4()),
        contract_id=contract.contract_id,
        contract_version=contract.version,
        contract_fingerprint=contract.fingerprint,
        status=overall,
        evaluated_at=evaluated_at or datetime.now(timezone.utc),
        checks=tuple(checks),
    )
