"""Orchestrate P3-21 evidence execution before the P3-20 gate."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable, Protocol

from domain.architecture_contract_v1 import ArchitectureContractV1
from domain.distribution import DispatchRecord
from domain.verification import DeliveredProduct, Evidence, VerificationResult
from services.architecture_dependency_adapter import architecture_dependency_adapter
from services.verification_execution import ExecutionBinding, VerificationExecutionError
from services.verification_service import VerificationService


class EvidenceAdapter(Protocol):
    """Minimal contract for P3-21 evidence producers."""

    def run(self, binding: ExecutionBinding, *, cwd: str | Path) -> Evidence:
        ...


class VerificationExecutionService:
    """Execute trusted evidence adapters, then delegate judgment to P3-20."""

    def __init__(self, verifier: VerificationService | None = None) -> None:
        self._verifier = verifier or VerificationService()

    def execute(
        self,
        dispatch: DispatchRecord,
        product: DeliveredProduct,
        *,
        cwd: str | Path,
        adapters: Iterable[EvidenceAdapter] = (),
        architecture_contract: ArchitectureContractV1 | None = None,
    ) -> tuple[DeliveredProduct, VerificationResult]:
        """Run adapters and verify the delivered product.

        When ``architecture_contract`` is provided, the canonical architecture
        dependency adapter is executed first and contributes Evidence(kind=
        "architecture"). Callers may still pass additional adapters (test, audit,
        security, provenance, ...).

        At least one evidence source is required: either explicit adapters,
        an architecture_contract, or both.
        """
        adapter_list: list[EvidenceAdapter] = []
        if architecture_contract is not None:
            adapter_list.append(architecture_dependency_adapter(architecture_contract))
        adapter_list.extend(tuple(adapters))

        if not adapter_list:
            raise VerificationExecutionError(
                "At least one verification adapter or architecture_contract is required"
            )

        binding = ExecutionBinding(
            package_fingerprint=dispatch.package_fingerprint,
            contract_fingerprint=dispatch.contract_fingerprint,
            dispatch_fingerprint=dispatch.fingerprint,
            artifact_fingerprint=product.artifact_fingerprint,
        )
        evidence: list[Evidence] = []
        for adapter in adapter_list:
            evidence.append(adapter.run(binding, cwd=cwd))

        delivered = replace(product, evidence=product.evidence + tuple(evidence))
        result = self._verifier.verify(dispatch, delivered)
        return delivered, result
