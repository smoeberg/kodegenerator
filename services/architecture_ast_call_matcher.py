"""Structured AST matching for forbid_call architecture constraints."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from services.architecture_dependency_evaluator import normalize_repo_path


@dataclass(frozen=True)
class CallMatch:
    path: str
    line: int
    callee: str
    message: str


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts: list[str] = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
            return ".".join(reversed(parts))
        return ".".join(reversed(parts))
    return None


def _const_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _keywords_match(node: ast.Call, required: Mapping[str, Any]) -> bool:
    if not required:
        return True
    found: dict[str, Any] = {}
    for kw in node.keywords:
        if kw.arg is None:
            continue
        val = _const_value(kw.value)
        if val is not None:
            found[kw.arg] = val
    for key, expected in required.items():
        if key not in found or found[key] != expected:
            return False
    return True


def _name_matches(name: str, target: str) -> bool:
    if name == target:
        return True
    # subprocess.call matches call only when target has no dots? No — require precision.
    # Allow target "subprocess.call" to match name "subprocess.call".
    # Allow target "call" only as exact last segment when target has no module.
    if "." in target:
        return name == target or name.endswith("." + target)
    return name == target or name.split(".")[-1] == target


def find_forbidden_calls(
    source: str,
    *,
    path: str,
    callee: str,
    keywords: Mapping[str, Any] | None = None,
) -> list[CallMatch]:
    """Return matches for callee (e.g. subprocess.call) with optional keyword constraints."""
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []

    required = dict(keywords or {})
    matches: list[CallMatch] = []
    target = callee.strip()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None or not _name_matches(name, target):
            continue
        if not _keywords_match(node, required):
            continue
        line = getattr(node, "lineno", 1)
        kw_desc = ", ".join(f"{k}={v!r}" for k, v in required.items())
        detail = f" with {kw_desc}" if kw_desc else ""
        matches.append(
            CallMatch(
                path=path,
                line=line,
                callee=name,
                message=f"Forbidden call {name}{detail} at {path}:{line}",
            )
        )
    return matches


def scan_file_for_forbidden_call(
    file_path: Path,
    *,
    root: Path,
    callee: str,
    keywords: Mapping[str, Any] | None = None,
) -> list[CallMatch]:
    rel = normalize_repo_path(file_path.resolve().relative_to(root.resolve()).as_posix())
    text = file_path.read_text(encoding="utf-8")
    return find_forbidden_calls(text, path=rel, callee=callee, keywords=keywords)
