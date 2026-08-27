"""Compile structured requirements into deterministic LLM execution contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from services.context_engine import ContextEngine, ContextPackage


class TaskCompilerError(ValueError):
    """A requirement cannot be compiled safely."""


@dataclass(frozen=True)
class Requirement:
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    target_module: str


@dataclass(frozen=True)
class AtomicTestSpecification:
    test_id: str
    criterion: str
    test_name: str
    expected_behavior: str


@dataclass(frozen=True)
class PromptContract:
    role: str
    objective: str
    constraints: tuple[str, ...]
    required_output: tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class CompiledTask:
    compiler_version: str
    task_id: str
    requirement: Requirement
    test_specifications: tuple[AtomicTestSpecification, ...]
    context: ContextPackage
    test_synthesizer: PromptContract
    code_synthesizer: PromptContract

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )


class TaskCompiler:
    """Turn one validated requirement into reproducible test/code prompts."""

    VERSION = "1.0"

    def __init__(
        self,
        repository_root: Path | str,
        *,
        context_token_budget: int = 4_000,
    ) -> None:
        self._context = ContextEngine(repository_root, token_budget=context_token_budget)

    def load_requirement(self, source: Path | str | Mapping[str, Any]) -> Requirement:
        if isinstance(source, Mapping):
            payload = dict(source)
        else:
            path = Path(source)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise TaskCompilerError(f"cannot load requirement: {type(exc).__name__}") from exc
            if not isinstance(payload, dict):
                raise TaskCompilerError("requirement JSON must contain an object")
        required = {"title", "description", "acceptance_criteria", "target_module"}
        missing = sorted(required - payload.keys())
        if missing:
            raise TaskCompilerError(f"requirement is missing fields: {', '.join(missing)}")
        raw_criteria = payload["acceptance_criteria"]
        if isinstance(raw_criteria, str) or not isinstance(raw_criteria, Sequence):
            raise TaskCompilerError("acceptance_criteria must be a non-empty sequence")
        criteria = tuple(self._text(value, "acceptance criterion") for value in raw_criteria)
        if not criteria:
            raise TaskCompilerError("acceptance_criteria must not be empty")
        return Requirement(
            self._text(payload["title"], "title"),
            self._text(payload["description"], "description"),
            criteria,
            self._target_module(payload["target_module"]),
        )

    def compile(self, source: Path | str | Mapping[str, Any]) -> CompiledTask:
        requirement = self.load_requirement(source)
        specifications = self._test_specifications(requirement.acceptance_criteria)
        context = self._context.build_context(
            target_module=requirement.target_module,
            query=" ".join(
                (requirement.title, requirement.description, *requirement.acceptance_criteria)
            ),
        )
        canonical = json.dumps(
            asdict(requirement), ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
        return CompiledTask(
            compiler_version=self.VERSION,
            task_id=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            requirement=requirement,
            test_specifications=specifications,
            context=context,
            test_synthesizer=self._prompt("Test", requirement, specifications, context),
            code_synthesizer=self._prompt("Code", requirement, specifications, context),
        )

    compile_requirement = compile

    @staticmethod
    def _text(value: Any, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise TaskCompilerError(f"{field_name} must be a non-empty string")
        return " ".join(value.split())

    @staticmethod
    def _target_module(value: Any) -> str:
        module = TaskCompiler._text(value, "target_module").replace("\\", "/")
        path = Path(module)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".py":
            raise TaskCompilerError("target_module must be a relative Python file path")
        return path.as_posix()

    @staticmethod
    def _test_specifications(
        criteria: tuple[str, ...],
    ) -> tuple[AtomicTestSpecification, ...]:
        specifications: list[AtomicTestSpecification] = []
        for position, criterion in enumerate(criteria, start=1):
            slug = re.sub(r"[^a-z0-9]+", "_", criterion.lower()).strip("_")[:64]
            digest = hashlib.sha256(f"{position}:{criterion}".encode()).hexdigest()[:12]
            specifications.append(
                AtomicTestSpecification(
                    test_id=f"ac-{position:03d}-{digest}",
                    criterion=criterion,
                    test_name=f"test_{slug or f'criterion_{position}'}",
                    expected_behavior=criterion,
                )
            )
        return tuple(specifications)

    @staticmethod
    def _context_text(context: ContextPackage) -> str:
        if not context.signatures:
            return "No verified repository symbols found. Do not invent imports."
        return "\n".join(
            f"- {record.module}: {record.signature}" for record in context.signatures
        )

    def _prompt(
        self,
        kind: str,
        requirement: Requirement,
        specifications: tuple[AtomicTestSpecification, ...],
        context: ContextPackage,
    ) -> PromptContract:
        is_test = kind == "Test"
        constraints = (
            (
                "Generate executable pytest tests; no placeholders or unconditional assertions.",
                "Test every acceptance criterion independently, including failure paths.",
                "Import only verified repository symbols or the target module.",
            )
            if is_test
            else (
                "Implement production code; no pseudocode, stubs, TODOs, or pass-only bodies.",
                "Satisfy every atomic specification and preserve public interfaces.",
                "Use only verified repository signatures; do not hallucinate imports.",
                "Fail closed on invalid input and avoid unrelated changes.",
            )
        )
        outputs = (
            ("Complete pytest source", "Deterministic fixtures", "One test per test_id")
            if is_test
            else (f"Complete {requirement.target_module}", "No unrelated files", "Passing tests")
        )
        tests = "\n".join(
            f"- {spec.test_id} {spec.test_name}: {spec.criterion}" for spec in specifications
        )
        prompt = (
            f"ROLE: {kind} Synthesizer\nTARGET: {requirement.target_module}\n"
            f"TITLE: {requirement.title}\nDESCRIPTION: {requirement.description}\n"
            f"ATOMIC SPECIFICATIONS:\n{tests}\nREPOSITORY SIGNATURES:\n"
            f"{self._context_text(context)}\nCONSTRAINTS:\n- " + "\n- ".join(constraints)
        )
        return PromptContract(
            f"{kind.lower()}_synthesizer",
            "Produce complete executable tests" if is_test else "Implement the requirement completely",
            constraints,
            outputs,
            prompt,
        )
