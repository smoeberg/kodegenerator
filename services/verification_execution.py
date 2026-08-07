"""P3-21 execution adapters for producing bound verification evidence.

Adapters execute fixed, allow-listed commands and never decide architecture,
route work, or interpret results through an LLM.  They only turn an external
execution result into the P3-20 Evidence contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Sequence

from domain.verification import Evidence, VerificationError


class VerificationExecutionError(RuntimeError):
    """Raised when an evidence adapter cannot execute safely."""


@dataclass(frozen=True)
class ExecutionBinding:
    """Immutable identity required to bind execution evidence to a product."""

    package_fingerprint: str
    contract_fingerprint: str
    dispatch_fingerprint: str
    artifact_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("package_fingerprint", self.package_fingerprint),
            ("contract_fingerprint", self.contract_fingerprint),
            ("dispatch_fingerprint", self.dispatch_fingerprint),
            ("artifact_fingerprint", self.artifact_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise VerificationExecutionError(f"{name} must be non-empty")


@dataclass(frozen=True)
class CommandEvidenceAdapter:
    """Execute one fixed command and convert its exit status into Evidence.

    The command is immutable and supplied by trusted application code.  User
    input must never be interpolated into ``command``.  Output is deliberately
    not copied into Evidence; the contract records only the deterministic
    execution identity and pass/fail result.
    """

    adapter_id: str
    kind: str
    command: tuple[str, ...]
    timeout_seconds: int = 300

    def __post_init__(self) -> None:
        if not self.adapter_id.strip():
            raise VerificationExecutionError("adapter_id must be non-empty")
        if self.kind not in {"test", "audit", "security", "architecture", "requirements", "provenance"}:
            raise VerificationExecutionError(f"Unsupported evidence kind: {self.kind}")
        if not self.command or any(not isinstance(item, str) or not item for item in self.command):
            raise VerificationExecutionError("command must contain non-empty arguments")
        if self.timeout_seconds <= 0:
            raise VerificationExecutionError("timeout_seconds must be positive")

    @property
    def execution_id(self) -> str:
        payload = {"adapter_id": self.adapter_id, "kind": self.kind, "command": list(self.command)}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "execution-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]

    def run(self, binding: ExecutionBinding, *, cwd: str | Path) -> Evidence:
        if not isinstance(binding, ExecutionBinding):
            raise VerificationExecutionError("run requires an ExecutionBinding")
        workspace = Path(cwd)
        if not workspace.is_dir():
            raise VerificationExecutionError("Execution cwd must be an existing directory")

        try:
            completed = subprocess.run(
                self.command,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise VerificationExecutionError(
                f"Verification command timed out after {self.timeout_seconds}s"
            ) from exc
        except OSError as exc:
            raise VerificationExecutionError(f"Verification command could not start: {exc}") from exc

        passed = completed.returncode == 0
        statement = (
            f"{self.adapter_id} completed with exit code {completed.returncode}"
            if passed
            else f"{self.adapter_id} failed with exit code {completed.returncode}"
        )
        return Evidence(
            kind=self.kind,
            evidence_id=self.execution_id,
            passed=passed,
            statement=statement,
            package_fingerprint=binding.package_fingerprint,
            contract_fingerprint=binding.contract_fingerprint,
            dispatch_fingerprint=binding.dispatch_fingerprint,
            artifact_fingerprint=binding.artifact_fingerprint,
        )


def pytest_adapter() -> CommandEvidenceAdapter:
    """Return the canonical project test adapter."""
    return CommandEvidenceAdapter("pytest", "test", ("python", "-m", "pytest", "-q"))


def compileall_adapter() -> CommandEvidenceAdapter:
    """Return the canonical Python compilation adapter."""
    return CommandEvidenceAdapter("compileall", "architecture", ("python", "-m", "compileall", "-q", "."))


def bandit_adapter() -> CommandEvidenceAdapter:
    """Return the canonical security adapter."""
    return CommandEvidenceAdapter("bandit", "security", ("python", "-m", "bandit", "-q", "-r", "."))


def provenance_adapter() -> CommandEvidenceAdapter:
    """Return the canonical provenance adapter using Git's immutable identity."""
    return CommandEvidenceAdapter("provenance", "provenance", ("git", "rev-parse", "HEAD"))
