"""Budgeted AST repository context for deterministic code synthesis."""

from __future__ import annotations

import ast
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path


class ContextEngineError(ValueError):
    """Repository context cannot be collected safely."""


@dataclass(frozen=True)
class SignatureRecord:
    module: str
    qualified_name: str
    kind: str
    signature: str
    relevance: int
    estimated_tokens: int


@dataclass(frozen=True)
class ContextPackage:
    repository_root: str
    target_module: str
    token_budget: int
    estimated_tokens: int
    truncated: bool
    signatures: tuple[SignatureRecord, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ContextEngine:
    """Extract relevant public signatures without exposing complete source files."""

    _EXCLUDED = frozenset(
        {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"}
    )

    def __init__(
        self,
        repository_root: Path | str,
        *,
        token_budget: int = 4_000,
        max_files: int = 2_000,
    ) -> None:
        root = Path(repository_root).resolve(strict=True)
        if not root.is_dir():
            raise ContextEngineError("repository_root must be an existing directory")
        if type(token_budget) is not int or token_budget < 1:
            raise ContextEngineError("token_budget must be a positive integer")
        if type(max_files) is not int or max_files < 1:
            raise ContextEngineError("max_files must be a positive integer")
        self._root = root
        self._token_budget = token_budget
        self._max_files = max_files

    def build_context(self, *, target_module: str, query: str = "") -> ContextPackage:
        target = self._safe_target(target_module)
        terms = self._terms(f"{query} {target.stem} {target.parent.as_posix()}")
        candidates: list[SignatureRecord] = []
        scanned = 0
        exhausted_file_budget = False
        for path in sorted(self._root.rglob("*.py")):
            if any(part in self._EXCLUDED for part in path.relative_to(self._root).parts):
                continue
            if scanned >= self._max_files:
                exhausted_file_budget = True
                break
            scanned += 1
            candidates.extend(self._signatures(path, target, terms))
        candidates.sort(
            key=lambda item: (-item.relevance, item.module, item.qualified_name, item.signature)
        )
        selected: list[SignatureRecord] = []
        consumed = 0
        omitted_for_tokens = False
        for item in candidates:
            if consumed + item.estimated_tokens > self._token_budget:
                omitted_for_tokens = True
                continue
            selected.append(item)
            consumed += item.estimated_tokens
        return ContextPackage(
            repository_root=str(self._root),
            target_module=target.as_posix(),
            token_budget=self._token_budget,
            estimated_tokens=consumed,
            truncated=exhausted_file_budget or omitted_for_tokens,
            signatures=tuple(selected),
        )

    collect = build_context

    @staticmethod
    def _safe_target(value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ContextEngineError("target_module must be a non-empty relative path")
        target = Path(value.replace("\\", "/"))
        if target.is_absolute() or ".." in target.parts or target.suffix != ".py":
            raise ContextEngineError("target_module must be a relative Python file path")
        return target

    @staticmethod
    def _terms(value: str) -> frozenset[str]:
        ignored = {"the", "and", "for", "with", "from", "that"}
        return frozenset(
            term
            for term in re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", value.lower())
            if term not in ignored
        )

    def _signatures(
        self,
        path: Path,
        target: Path,
        terms: frozenset[str],
    ) -> list[SignatureRecord]:
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                return []
            if info.st_size > 1_000_000:
                return []
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            return []
        relative = path.relative_to(self._root)
        module = relative.as_posix()
        base_score = 80 if relative == target else 30 if relative.parent == target.parent else 0
        base_score += 8 * len(self._terms(module) & terms)
        records: list[SignatureRecord] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                records.append(self._record(module, node.name, "function", self._function_signature(node), base_score, terms))
            elif isinstance(node, ast.ClassDef):
                records.append(self._record(module, node.name, "class", self._class_signature(node), base_score, terms))
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("__"):
                        records.append(
                            self._record(
                                module,
                                f"{node.name}.{child.name}",
                                "method",
                                self._function_signature(child, owner=node.name),
                                base_score + 3,
                                terms,
                            )
                        )
        return [record for record in records if record.relevance > 0]

    @staticmethod
    def _record(
        module: str,
        name: str,
        kind: str,
        signature: str,
        base_score: int,
        terms: frozenset[str],
    ) -> SignatureRecord:
        relevance = base_score + 12 * len(ContextEngine._terms(name) & terms)
        estimated_tokens = max(1, (len(module) + len(signature) + 4) // 4)
        return SignatureRecord(module, name, kind, signature, relevance, estimated_tokens)

    @staticmethod
    def _function_signature(
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        owner: str | None = None,
    ) -> str:
        arguments: list[str] = []
        positional = [*node.args.posonlyargs, *node.args.args]
        defaults_at = len(positional) - len(node.args.defaults)
        for index, argument in enumerate(positional):
            value = argument.arg
            if argument.annotation is not None:
                value += f": {ast.unparse(argument.annotation)}"
            if index >= defaults_at:
                value += f" = {ast.unparse(node.args.defaults[index - defaults_at])}"
            arguments.append(value)
        if node.args.vararg is not None:
            arguments.append(f"*{node.args.vararg.arg}")
        elif node.args.kwonlyargs:
            arguments.append("*")
        for argument, default in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True):
            value = argument.arg
            if argument.annotation is not None:
                value += f": {ast.unparse(argument.annotation)}"
            if default is not None:
                value += f" = {ast.unparse(default)}"
            arguments.append(value)
        if node.args.kwarg is not None:
            arguments.append(f"**{node.args.kwarg.arg}")
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        name = f"{owner}.{node.name}" if owner else node.name
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        return f"{prefix} {name}({', '.join(arguments)}){returns}"

    @staticmethod
    def _class_signature(node: ast.ClassDef) -> str:
        bases = [ast.unparse(base) for base in node.bases]
        suffix = f"({', '.join(bases)})" if bases else ""
        return f"class {node.name}{suffix}"
