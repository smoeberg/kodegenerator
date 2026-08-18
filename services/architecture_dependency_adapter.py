"""P3-21 style evidence adapter for Architecture Contract v1 verification.

Runs unified architecture verification (import-graph dependency rules + AST
constraints) and emits bound Evidence(kind="architecture") for the P3-20 gate.
No LLM calls. Fail-closed on parse/evaluation errors.

Binding semantics:
- Evidence.contract_fingerprint is the *dispatch/specialist* contract fingerprint
  required by P3-20 evidence binding.
- ArchitectureContractV1.fingerprint is recorded in execution identity and statement
  for auditability; it is a different identity from the specialist contract.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from domain.architecture_contract_v1 import ArchitectureContractV1
from domain.verification import Evidence
from services.architecture_verification import (
    ArchitectureVerificationError,
    verify_architecture,
)
from services.verification_execution import ExecutionBinding, VerificationExecutionError


@dataclass(frozen=True)
class ArchitectureDependencyEvidenceAdapter:
    """Produce architecture verification evidence for one fixed architecture contract."""

    contract: ArchitectureContractV1
    adapter_id: str = "architecture-verification-v1"

    def __post_init__(self) -> None:
        if not isinstance(self.contract, ArchitectureContractV1):
            raise VerificationExecutionError("contract must be ArchitectureContractV1")
        if not self.adapter_id.strip():
            raise VerificationExecutionError("adapter_id must be non-empty")

    @property
    def execution_id(self) -> str:
        payload = {
            "adapter_id": self.adapter_id,
            "kind": "architecture",
            "architecture_contract_id": self.contract.contract_id,
            "architecture_contract_version": self.contract.version,
            "architecture_contract_fingerprint": self.contract.fingerprint,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "execution-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]

    def evaluate_workspace(self, cwd: str | Path):
        """Return the unified architecture verification result for a workspace."""
        workspace = Path(cwd)
        if not workspace.is_dir():
            raise VerificationExecutionError("Execution cwd must be an existing directory")
        try:
            return verify_architecture(self.contract, workspace)
        except ArchitectureVerificationError as exc:
            raise VerificationExecutionError(str(exc)) from exc

    def run(self, binding: ExecutionBinding, *, cwd: str | Path) -> Evidence:
        if not isinstance(binding, ExecutionBinding):
            raise VerificationExecutionError("run requires an ExecutionBinding")

        try:
            result = self.evaluate_workspace(cwd)
        except VerificationExecutionError as exc:
            return Evidence(
                kind="architecture",
                evidence_id=self.execution_id,
                passed=False,
                statement=f"{self.adapter_id} failed closed: {exc}",
                package_fingerprint=binding.package_fingerprint,
                contract_fingerprint=binding.contract_fingerprint,
                dispatch_fingerprint=binding.dispatch_fingerprint,
                artifact_fingerprint=binding.artifact_fingerprint,
            )

        failed = [c for c in result.checks if c.status == "FAIL"]
        passed = result.status == "PASS"
        arch_ref = (
            f"architecture {self.contract.contract_id}@{self.contract.version} "
            f"fp={self.contract.fingerprint[:12]}"
        )
        if passed:
            statement = (
                f"{self.adapter_id} PASS: {result.summary['passed']} checks, "
                f"0 block failures ({arch_ref})"
            )
        else:
            sample = failed[0].message if failed else "architecture verification failed"
            statement = (
                f"{self.adapter_id} FAIL: {result.summary['failed']} block failures; "
                f"example: {sample} ({arch_ref})"
            )

        return Evidence(
            kind="architecture",
            evidence_id=self.execution_id,
            passed=passed,
            statement=statement,
            package_fingerprint=binding.package_fingerprint,
            contract_fingerprint=binding.contract_fingerprint,
            dispatch_fingerprint=binding.dispatch_fingerprint,
            artifact_fingerprint=binding.artifact_fingerprint,
        )


def architecture_dependency_adapter(
    contract: ArchitectureContractV1,
) -> ArchitectureDependencyEvidenceAdapter:
    """Factory for the canonical architecture verification evidence adapter."""
    return ArchitectureDependencyEvidenceAdapter(contract=contract)
