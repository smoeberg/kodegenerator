"""Governed code patch synthesizer with AST validation and sandbox verification.

Pipeline (fail-closed):
  1. Verify ``VerifiedAuthorityGrant`` (ALLOW, unexpired, matching action).
  2. Synthesize Python source / unified diff for the task + architecture spec.
  3. Validate with ``ast.parse`` and forbidden-node policy (and optional contract gate).
  4. Execute syntax/verification in a Phase 6 sandbox adapter.
  5. Approve only when AST and sandbox both succeed.

A failed AST check or sandbox run never yields an approved merge candidate.
"""
from __future__ import annotations

import ast
import hashlib
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from domain.task import Task
from phase4.authority.grants import VerifiedAuthorityGrant
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionOutcome,
    ExecutionResult,
    ExecutionSecurityContext,
    ExecutionSpec,
)


SYNTHESIZE_ACTION = "code.patch.synthesize"
FORBIDDEN_CALL_NAMES = frozenset(
    {"eval", "exec", "compile", "__import__", "input", "breakpoint", "system", "popen", "remove", "unlink"}
)
FORBIDDEN_ATTR_CALLEES = frozenset(
    {
        ("os", "system"),
        ("os", "popen"),
        ("subprocess", "call"),
        ("subprocess", "run"),
        ("subprocess", "Popen"),
        ("pathlib.Path", "unlink"),
    }
)


class PatchSynthesisError(RuntimeError):
    pass


class AuthorityGrantError(PatchSynthesisError):
    pass


class AstValidationError(PatchSynthesisError):
    pass


class SandboxVerificationError(PatchSynthesisError):
    pass


class ContractGateError(PatchSynthesisError):
    pass


@dataclass(frozen=True)
class ArchitectureSpec:
    contract_id: str
    version: str
    module_name: str
    status: str = "approved"
    public_functions: tuple[str, ...] = ("run",)
    human_approved_by: str = "architecture-board"
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.contract_id.strip() or not self.version.strip():
            raise ValueError("architecture contract_id and version are required")
        if not self.module_name.isidentifier():
            raise ValueError("module_name must be a valid Python identifier")
        if not self.public_functions:
            raise ValueError("public_functions must not be empty")

    @property
    def fingerprint(self) -> str:
        payload = (
            f"{self.contract_id}|{self.version}|{self.module_name}|"
            f"{','.join(self.public_functions)}|{self.status}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PatchSynthesisResult:
    approved: bool
    task_id: str
    module_name: str
    source_code: str
    patch_diff: str
    ast_ok: bool
    sandbox_ok: bool
    grant_id: str
    architecture_fingerprint: str
    error: str | None = None
    sandbox_output: str = ""
    source_fingerprint: str = ""
    provenance_id: str = ""

    def __post_init__(self) -> None:
        if self.approved and not (self.ast_ok and self.sandbox_ok):
            raise ValueError("approved result requires ast_ok and sandbox_ok")


class SandboxExecutor(Protocol):
    adapter_id: str

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        ...


SourceRenderer = Callable[[Task, ArchitectureSpec], str]
ContractGate = Callable[[Task, ArchitectureSpec], None]


def _default_renderer(task: Task, architecture: ArchitectureSpec) -> str:
    fn = architecture.public_functions[0]
    doc = (task.description or task.name or task.id).replace('"""', "'")
    return textwrap.dedent(
        f'''\
        """Governed module for task {task.id}.

        Architecture: {architecture.contract_id}@{architecture.version}
        """

        def {fn}(payload: dict | None = None) -> dict:
            """{doc}"""
            data = dict(payload or {{}})
            data.setdefault("task_id", {task.id!r})
            data.setdefault("module", {architecture.module_name!r})
            data["status"] = "ok"
            return data


        def main() -> None:
            print({fn}({{"source": "sandbox"}}))


        if __name__ == "__main__":
            main()
        '''
    )


def _default_contract_gate(task: Task, architecture: ArchitectureSpec) -> None:
    if architecture.status != "approved":
        raise ContractGateError(
            f"architecture {architecture.contract_id} is not approved (status={architecture.status!r})"
        )
    if not architecture.human_approved_by.strip():
        raise ContractGateError("architecture lacks human_approved_by")
    if not task.id or not str(task.id).strip():
        raise ContractGateError("task id is required for contract binding")


@dataclass
class CodePatchSynthesizer:
    sandbox: SandboxExecutor
    python_executable: str = "/usr/bin/python3"
    allowed_action: str = SYNTHESIZE_ACTION
    renderer: SourceRenderer = field(default=_default_renderer)
    contract_gate: ContractGate = field(default=_default_contract_gate)
    limits: ExecutionLimits = field(
        default_factory=lambda: ExecutionLimits(
            wall_time_seconds=10.0,
            cpu_time_seconds=5.0,
            memory_bytes=64 * 1024 * 1024,
            process_count=1,
            output_bytes=256 * 1024,
            file_size_bytes=1024 * 1024,
            open_file_count=32,
        )
    )

    def synthesize(
        self,
        task: Task,
        architecture: ArchitectureSpec,
        grant: VerifiedAuthorityGrant,
        *,
        organization_id: str | None = None,
        principal_id: str = "synthesizer",
        actor_id: str = "code-patch-synthesizer",
    ) -> PatchSynthesisResult:
        self._assert_grant(grant, task=task, architecture=architecture)

        try:
            self.contract_gate(task, architecture)
        except ContractGateError as exc:
            return self._rejected(
                task=task, architecture=architecture, grant=grant,
                source_code="", patch_diff="", ast_ok=False, sandbox_ok=False, error=str(exc),
            )

        source = self.renderer(task, architecture)
        patch_diff = self._unified_diff(architecture.module_name, source)

        try:
            self._validate_ast(source)
        except AstValidationError as exc:
            return self._rejected(
                task=task, architecture=architecture, grant=grant,
                source_code=source, patch_diff=patch_diff,
                ast_ok=False, sandbox_ok=False, error=str(exc),
            )

        try:
            sandbox_result = self._run_sandbox(
                source=source,
                module_name=architecture.module_name,
                grant=grant,
                organization_id=organization_id or grant.organization_id or "org:unknown",
                principal_id=principal_id,
                actor_id=actor_id,
            )
        except (SandboxVerificationError, OSError, ValueError) as exc:
            return self._rejected(
                task=task, architecture=architecture, grant=grant,
                source_code=source, patch_diff=patch_diff,
                ast_ok=True, sandbox_ok=False, error=str(exc),
            )

        if sandbox_result.outcome is not ExecutionOutcome.SUCCEEDED:
            return self._rejected(
                task=task, architecture=architecture, grant=grant,
                source_code=source, patch_diff=patch_diff,
                ast_ok=True, sandbox_ok=False,
                error=sandbox_result.error or f"sandbox outcome={sandbox_result.outcome.value}",
                sandbox_output=sandbox_result.output,
            )

        source_fp = hashlib.sha256(source.encode("utf-8")).hexdigest()
        provenance_id = hashlib.sha256(
            f"{grant.grant_id}|{task.id}|{architecture.fingerprint}|{source_fp}".encode()
        ).hexdigest()
        return PatchSynthesisResult(
            approved=True,
            task_id=str(task.id),
            module_name=architecture.module_name,
            source_code=source,
            patch_diff=patch_diff,
            ast_ok=True,
            sandbox_ok=True,
            grant_id=grant.grant_id,
            architecture_fingerprint=architecture.fingerprint,
            source_fingerprint=source_fp,
            provenance_id=provenance_id,
            sandbox_output=sandbox_result.output,
        )

    def _assert_grant(self, grant, *, task, architecture) -> None:
        if grant is None:
            raise AuthorityGrantError("VerifiedAuthorityGrant is required")
        if not grant.verify():
            raise AuthorityGrantError("authority grant failed verification or is expired")
        if grant.decision != "allow":
            raise AuthorityGrantError("authority grant decision is not allow")
        if grant.action != self.allowed_action:
            raise AuthorityGrantError(
                f"grant action {grant.action!r} is not {self.allowed_action!r}"
            )
        resource = grant.resource or ""
        if (
            architecture.module_name not in resource
            and str(task.id) not in resource
            and "patch" not in resource
        ):
            raise AuthorityGrantError(
                f"grant resource {resource!r} is not bound to task/module under synthesis"
            )

    def _validate_ast(self, source: str) -> ast.AST:
        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            raise AstValidationError(f"AST parse failed: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name in FORBIDDEN_CALL_NAMES:
                    raise AstValidationError(f"forbidden call: {name}")
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    pair = (node.func.value.id, node.func.attr)
                    if pair in FORBIDDEN_ATTR_CALLEES:
                        raise AstValidationError(f"forbidden call: {pair[0]}.{pair[1]}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    modules = [alias.name.split(".")[0] for alias in node.names]
                else:
                    modules = [node.module.split(".")[0]] if node.module else []
                bad = {"subprocess", "ctypes", "importlib"}.intersection(modules)
                if bad:
                    raise AstValidationError(f"forbidden import: {sorted(bad)}")
        return tree

    @staticmethod
    def _call_name(func: ast.AST) -> str | None:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            return func.attr
        return None

    def _run_sandbox(self, *, source, module_name, grant, organization_id, principal_id, actor_id):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="dor-patch-") as tmp:
            module_path = Path(tmp) / f"{module_name}.py"
            module_path.write_text(source, encoding="utf-8")
            spec = ExecutionSpec(
                execution_id=f"synth-{grant.grant_id[:12]}",
                adapter_id=getattr(self.sandbox, "adapter_id", "sandbox"),
                argv=(self.python_executable, "-m", "py_compile", str(module_path)),
                security=ExecutionSecurityContext(
                    organization_id=organization_id,
                    principal_id=principal_id,
                    actor_id=actor_id,
                    capabilities=("code.patch.verify",),
                ),
                limits=self.limits,
                network_allowlist=(),
                environment=(("PYTHONDONTWRITEBYTECODE", "1"),),
            )
            result = self.sandbox.execute(spec)
            if result.outcome is not ExecutionOutcome.SUCCEEDED:
                raise SandboxVerificationError(
                    result.error or f"sandbox verification failed with {result.outcome.value}"
                )
            return result

    @staticmethod
    def _unified_diff(module_name: str, source: str) -> str:
        lines = source.splitlines()
        header = [
            "--- /dev/null",
            f"+++ b/{module_name}.py",
            f"@@ -0,0 +1,{len(lines)} @@",
        ]
        return "\n".join(header + [f"+{line}" for line in lines]) + "\n"

    @staticmethod
    def _rejected(*, task, architecture, grant, source_code, patch_diff, ast_ok, sandbox_ok, error, sandbox_output=""):
        source_fp = hashlib.sha256(source_code.encode()).hexdigest() if source_code else ""
        return PatchSynthesisResult(
            approved=False,
            task_id=str(task.id),
            module_name=architecture.module_name,
            source_code=source_code,
            patch_diff=patch_diff,
            ast_ok=ast_ok,
            sandbox_ok=sandbox_ok,
            grant_id=getattr(grant, "grant_id", "") or "",
            architecture_fingerprint=architecture.fingerprint,
            error=error,
            sandbox_output=sandbox_output,
            source_fingerprint=source_fp,
        )


@dataclass
class InProcessSandbox:
    """Test/dev sandbox without bubblewrap. Prod: inject BubblewrapProcessAdapter."""

    adapter_id: str = "inprocess-compile"
    allowed_executables: Sequence[str] = ("/usr/bin/python3", "python3", "python")
    force_fail: bool = False

    def execute(self, spec: ExecutionSpec) -> ExecutionResult:
        if self.force_fail:
            return ExecutionResult(
                execution_id=spec.execution_id,
                adapter_id=self.adapter_id,
                outcome=ExecutionOutcome.FAILED,
                error="forced sandbox failure",
                exit_code=1,
            )
        executable = spec.argv[0]
        allowed_names = {str(Path(e).name) for e in self.allowed_executables}
        if executable not in set(self.allowed_executables) and Path(executable).name not in allowed_names:
            return ExecutionResult(
                execution_id=spec.execution_id,
                adapter_id=self.adapter_id,
                outcome=ExecutionOutcome.REJECTED,
                error=f"executable not allowlisted: {executable}",
            )
        if len(spec.argv) >= 4 and spec.argv[1] == "-m" and spec.argv[2] == "py_compile":
            try:
                compile(Path(spec.argv[3]).read_text(encoding="utf-8"), spec.argv[3], "exec")
                return ExecutionResult(
                    execution_id=spec.execution_id,
                    adapter_id=self.adapter_id,
                    outcome=ExecutionOutcome.SUCCEEDED,
                    output="VERIFY_OK\n",
                    exit_code=0,
                )
            except Exception as exc:  # noqa: BLE001
                return ExecutionResult(
                    execution_id=spec.execution_id,
                    adapter_id=self.adapter_id,
                    outcome=ExecutionOutcome.FAILED,
                    error=str(exc),
                    exit_code=1,
                )
        return ExecutionResult(
            execution_id=spec.execution_id,
            adapter_id=self.adapter_id,
            outcome=ExecutionOutcome.REJECTED,
            error="unsupported argv form",
        )