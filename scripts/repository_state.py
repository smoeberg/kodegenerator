#!/usr/bin/env python3
"""Report and validate live repository state without trusting agent memory."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


class RepositoryStateError(RuntimeError):
    """Raised when repository state cannot be verified."""


def _run(root: Path, *command: str, check: bool = True) -> str:
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RepositoryStateError(f"{' '.join(command)} failed: {detail}")
    return result.stdout.strip()


def _literal_assignment(path: Path, name: str) -> Any:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            value = node.value
            if value is None:
                return None
            return ast.literal_eval(value)
    raise RepositoryStateError(f"{path} does not declare {name}")


def migration_heads(root: Path) -> list[str]:
    """Compute Alembic heads from revision declarations using the stdlib."""
    revisions: dict[str, Path] = {}
    parent_revisions: set[str] = set()
    versions = root / "alembic" / "versions"
    for path in sorted(versions.glob("*.py")):
        if path.name == "__init__.py":
            continue
        revision = _literal_assignment(path, "revision")
        down_revision = _literal_assignment(path, "down_revision")
        if not isinstance(revision, str) or not revision:
            raise RepositoryStateError(f"{path} has an invalid revision")
        if revision in revisions:
            raise RepositoryStateError(
                f"duplicate Alembic revision {revision}: {revisions[revision]} and {path}"
            )
        revisions[revision] = path
        if isinstance(down_revision, str):
            parent_revisions.add(down_revision)
        elif isinstance(down_revision, (tuple, list)):
            parent_revisions.update(str(value) for value in down_revision)
        elif down_revision is not None:
            raise RepositoryStateError(f"{path} has an invalid down_revision")
    if not revisions:
        raise RepositoryStateError("no Alembic revisions found")
    missing = sorted(parent_revisions - revisions.keys())
    if missing:
        raise RepositoryStateError(f"missing Alembic parent revisions: {missing}")
    return sorted(revisions.keys() - parent_revisions)


def load_contract(root: Path) -> dict[str, Any]:
    path = root / "docs" / "CURRENT_STATE.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepositoryStateError(f"cannot load {path}: {exc}") from exc
    if payload.get("schema_version") != 1:
        raise RepositoryStateError("unsupported CURRENT_STATE schema_version")
    return payload


def inspect_repository(root: Path, base: str, *, fetch: bool = False) -> dict[str, Any]:
    if fetch:
        _run(root, "git", "fetch", "origin", "--prune")
    _run(root, "git", "rev-parse", "--is-inside-work-tree")
    head = _run(root, "git", "rev-parse", "HEAD")
    base_sha = _run(root, "git", "rev-parse", base)
    branch = _run(root, "git", "branch", "--show-current") or "DETACHED"
    merge_base = _run(root, "git", "merge-base", base, "HEAD")
    counts = _run(root, "git", "rev-list", "--left-right", "--count", f"{base}...HEAD")
    try:
        behind_text, ahead_text = counts.split()
        behind, ahead = int(behind_text), int(ahead_text)
    except (ValueError, TypeError) as exc:
        raise RepositoryStateError(f"invalid ahead/behind result: {counts!r}") from exc
    dirty_paths = [
        line for line in _run(root, "git", "status", "--porcelain").splitlines() if line
    ]
    return {
        "classification": "VERIFIED",
        "branch": branch,
        "head_sha": head,
        "base_ref": base,
        "base_sha": base_sha,
        "merge_base_sha": merge_base,
        "ahead": ahead,
        "behind": behind,
        "dirty": bool(dirty_paths),
        "dirty_paths": dirty_paths,
        "alembic_heads": migration_heads(root),
    }


def validate_contract(root: Path, contract: dict[str, Any], report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected_head = contract.get("canonical_alembic_head")
    if report["alembic_heads"] != [expected_head]:
        errors.append(
            "canonical Alembic head mismatch: "
            f"expected {[expected_head]!r}, got {report['alembic_heads']!r}"
        )
    required_paths = [
        *contract.get("canonical_runtime_paths", []),
        *contract.get("required_workflows", []),
        contract.get("agent_protocol", ""),
    ]
    for relative_path in required_paths:
        if not relative_path or not (root / relative_path).is_file():
            errors.append(f"required canonical path is missing: {relative_path!r}")
    if contract.get("canonical_branch") != "main":
        errors.append("canonical_branch must remain 'main'")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main", help="fetched canonical base ref")
    parser.add_argument("--fetch", action="store_true", help="fetch origin before inspection")
    parser.add_argument("--validate", action="store_true", help="validate CURRENT_STATE invariants")
    parser.add_argument("--require-clean", action="store_true", help="reject a dirty worktree")
    parser.add_argument("--output", type=Path, help="optionally write the JSON report")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        contract = load_contract(root)
        report = inspect_repository(root, args.base, fetch=args.fetch)
        errors = validate_contract(root, contract, report) if args.validate else []
        if args.require_clean and report["dirty"]:
            errors.append("worktree is dirty")
        report["contract_status"] = "PASSED" if not errors else "FAILED"
        report["errors"] = errors
    except RepositoryStateError as exc:
        report = {
            "classification": "UNKNOWN",
            "contract_status": "FAILED",
            "errors": [str(exc)],
        }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report["contract_status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
