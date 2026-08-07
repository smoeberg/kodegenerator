"""Orchestrate P3-21 evidence execution before the P3-20 gate."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from domain.distribution import DispatchRecord
from domain.verification import DeliveredProduct, Evidence, VerificationResult
from services.verification_execution import CommandEvidenceAdapter, ExecutionBinding, VerificationExecutionError
from services.verification_service import VerificationService


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
        adapters: Iterable[CommandEvidenceAdapter],
    ) -> tuple[DeliveredProduct, VerificationResult]:
        adapter_list = tuple(adapters)
        if not adapter_list:
            raise VerificationExecutionError("At least one verification adapter is required")

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
