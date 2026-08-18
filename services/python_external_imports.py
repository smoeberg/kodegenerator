"""Collect external (non-repo) Python imports via AST for framework checks."""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable

from services.architecture_dependency_evaluator import normalize_repo_path
from services.python_import_graph import ImportGraphError, _build_module_index, _iter_python_files, _module_name_for_file


@dataclass(frozen=True)
class ExternalImport:
    source_path: str
    module: str  # top-level package, e.g. "fastapi"
    full_name: str  # e.g. "fastapi.routing"


def _stdlib_names() -> set[str]:
    names = set(getattr(sys, "stdlib_module_names", ()) or ())
    # Always treat common builtins / frozen as stdlib-ish.
    names.update({"__future__", "typing_extensions"})
    return names


def collect_external_imports(root: str | Path) -> list[ExternalImport]:
    """Return imports that do not resolve to files inside the workspace."""
    workspace = Path(root)
    if not workspace.is_dir():
        raise ImportGraphError(f"Root must be an existing directory: {root}")

    index = _build_module_index(workspace)
    stdlib = _stdlib_names()
    found: list[ExternalImport] = []
    seen: set[tuple[str, str]] = set()

    for source_path in _iter_python_files(workspace):
        try:
            source_text = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(source_path))
        except OSError as exc:
            raise ImportGraphError(f"Cannot read {source_path}: {exc}") from exc
        except SyntaxError as exc:
            raise ImportGraphError(f"Syntax error in {source_path}: {exc}") from exc

        rel = normalize_repo_path(
            source_path.resolve().relative_to(workspace.resolve()).as_posix()
        )
        names: set[str] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    continue  # relative imports are internal by construction
                if node.module:
                    names.add(node.module)

        for full_name in sorted(names):
            # Internal if any prefix resolves to a workspace module.
            parts = full_name.split(".")
            is_internal = False
            for i in range(len(parts), 0, -1):
                if ".".join(parts[:i]) in index:
                    is_internal = True
                    break
            if is_internal:
                continue
            top = parts[0]
            if top in stdlib:
                continue
            key = (rel, full_name)
            if key in seen:
                continue
            seen.add(key)
            found.append(ExternalImport(source_path=rel, module=top, full_name=full_name))

    return found
