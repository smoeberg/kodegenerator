"""Extract internal Python import edges via the standard AST module.

Only repository-local dependencies are emitted. External packages are ignored
so architecture dependency rules evaluate the project's own layer graph.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from services.architecture_dependency_evaluator import ImportEdge, normalize_repo_path


class ImportGraphError(ValueError):
    """Raised when a Python source file cannot be parsed safely."""


def _iter_python_files(root: Path) -> Iterable[Path]:
    skip_dirs = {
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
    for path in sorted(root.rglob("*.py")):
        if any(part in skip_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue
        yield path


def _module_name_for_file(root: Path, file_path: Path) -> str:
    rel = file_path.resolve().relative_to(root.resolve())
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1][:-3]  # strip .py
    return ".".join(parts)


def _build_module_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for file_path in _iter_python_files(root):
        module = _module_name_for_file(root, file_path)
        if module:
            index[module] = file_path
        # Also index package roots for `from package import module` resolution.
        if file_path.name == "__init__.py":
            package = _module_name_for_file(root, file_path)
            if package:
                index[package] = file_path
    return index


def _resolve_absolute_module(module: str, index: dict[str, Path]) -> Path | None:
    if module in index:
        return index[module]
    # Allow importing a package submodule that maps to a file.
    candidate = module
    while "." in candidate:
        candidate = candidate.rsplit(".", 1)[0]
        if candidate in index:
            # Prefer exact leaf if present; otherwise nearest package is not a file edge target.
            break
    # Try progressively longer prefixes for submodule files.
    parts = module.split(".")
    for i in range(len(parts), 0, -1):
        key = ".".join(parts[:i])
        if key in index:
            return index[key]
    return None


def _resolve_relative_module(
    current_module: str,
    level: int,
    module: str | None,
    index: dict[str, Path],
) -> Path | None:
    if level < 1:
        return None
    parts = current_module.split(".") if current_module else []
    # For a module file a.b.c, one leading dot starts at package a.b
    if level > len(parts):
        return None
    base_parts = parts[: len(parts) - level]
    if module:
        base_parts = base_parts + module.split(".")
    target = ".".join(part for part in base_parts if part)
    if not target:
        return None
    return _resolve_absolute_module(target, index)


def _repo_relative(root: Path, path: Path) -> str:
    return normalize_repo_path(path.resolve().relative_to(root.resolve()).as_posix())


def collect_import_edges(root: str | Path) -> list[ImportEdge]:
    """Return internal import edges for all Python files under ``root``.

    Edges are directed source_file -> target_file using repo-relative POSIX paths.
    Parse errors raise ImportGraphError (fail-closed).
    """
    workspace = Path(root)
    if not workspace.is_dir():
        raise ImportGraphError(f"Root must be an existing directory: {root}")

    index = _build_module_index(workspace)
    edges: list[ImportEdge] = []
    seen: set[tuple[str, str]] = set()

    for source_path in _iter_python_files(workspace):
        current_module = _module_name_for_file(workspace, source_path)
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ImportGraphError(f"Cannot read {source_path}: {exc}") from exc
        try:
            tree = ast.parse(source_text, filename=str(source_path))
        except SyntaxError as exc:
            raise ImportGraphError(f"Syntax error in {source_path}: {exc}") from exc

        source_rel = _repo_relative(workspace, source_path)
        targets: set[Path] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    resolved = _resolve_absolute_module(alias.name, index)
                    if resolved is not None:
                        targets.add(resolved)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    resolved = _resolve_relative_module(
                        current_module, node.level, node.module, index
                    )
                    if resolved is not None:
                        targets.add(resolved)
                elif node.module:
                    resolved = _resolve_absolute_module(node.module, index)
                    if resolved is not None:
                        targets.add(resolved)

        for target_path in sorted(targets, key=lambda p: p.as_posix()):
            if target_path.resolve() == source_path.resolve():
                continue
            target_rel = _repo_relative(workspace, target_path)
            key = (source_rel, target_rel)
            if key in seen:
                continue
            seen.add(key)
            edges.append(ImportEdge(source_path=source_rel, target_path=target_rel))

    return edges
