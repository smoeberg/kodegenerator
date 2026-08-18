"""P3-21 style evidence adapter for Architecture Contract v1 dependency rules.

Extracts a Python import graph from a workspace, evaluates it against an
ArchitectureContractV1, and emits bound Evidence(kind="architecture") for the
P3-20 verification gate. No LLM calls. Fail-closed on parse/evaluation errors.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from domain.architecture_contract_v1 import ArchitectureContractV1
from domain.verification import Evidence
from services.architecture_dependency_evaluator import evaluate_dependency_rules
from services.python_import_graph import ImportGraphError, collect_import_edges
from services.verification_execution import ExecutionBinding, VerificationExecutionError


@dataclass(frozen=True)
class ArchitectureDependencyEvidenceAdapter:
    """Produce architecture dependency evidence for one fixed contract identity."""

    contract: ArchitectureContractV1
    adapter_id: str = "architecture-dependency-v1"

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
            "contract_id": self.contract.contract_id,
            "contract_version": self.contract.version,
            "contract_fingerprint": self.contract.fingerprint,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "execution-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]

    def evaluate_workspace(self, cwd: str | Path):
        """Return the structured dependency evaluation for a workspace root."""
        workspace = Path(cwd)
        if not workspace.is_dir():
            raise VerificationExecutionError("Execution cwd must be an existing directory")
        try:
            edges = collect_import_edges(workspace)
        except ImportGraphError as exc:
            raise VerificationExecutionError(str(exc)) from exc
        return evaluate_dependency_rules(self.contract, edges)

    def run(self, binding: ExecutionBinding, *, cwd: str | Path) -> Evidence:
        if not isinstance(binding, ExecutionBinding):
            raise VerificationExecutionError("run requires an ExecutionBinding")

        # Evidence must remain bound to the delivery context. When an architecture
        # contract fingerprint is available on the binding, require an exact match.
        if binding.contract_fingerprint != self.contract.fingerprint:
            return Evidence(
                kind="architecture",
                evidence_id=self.execution_id,
                passed=False,
                statement=(
                    "Architecture contract fingerprint mismatch between binding and adapter "
                    f"(binding={binding.contract_fingerprint[:12]}…, "
                    f"adapter={self.contract.fingerprint[:12]}…)"
                ),
                package_fingerprint=binding.package_fingerprint,
                contract_fingerprint=binding.contract_fingerprint,
                dispatch_fingerprint=binding.dispatch_fingerprint,
                artifact_fingerprint=binding.artifact_fingerprint,
            )

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
        if passed:
            statement = (
                f"{self.adapter_id} PASS: {result.summary['passed']} checks, "
                f"0 block failures (contract {self.contract.contract_id}@{self.contract.version})"
            )
        else:
            sample = failed[0].message if failed else "dependency evaluation failed"
            statement = (
                f"{self.adapter_id} FAIL: {result.summary['failed']} block failures; "
                f"example: {sample}"
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
    """Factory for the canonical architecture dependency evidence adapter."""
    return ArchitectureDependencyEvidenceAdapter(contract=contract)
