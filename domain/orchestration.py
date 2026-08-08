"""P3-22 deterministic lifecycle orchestrator.

This layer coordinates P3-19 dispatch, specialist delivery, P3-21 execution,
and the P3-20 verification authority. It never interprets or overrides the
verification decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from domain.distribution import DispatchRecord
from domain.orchestration import (
    OrchestrationError,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationSnapshot,
    OrchestrationState,
)
from domain.verification import DeliveredProduct, VerificationResult
from services.verification_execution import CommandEvidenceAdapter, VerificationExecutionError
from services.verification_execution_service import VerificationExecutionService


class OrchestrationFailure(RuntimeError):
    """Raised only for unexpected orchestration infrastructure failures."""


@dataclass(frozen=True)
class OrchestrationOutcome:
    result: OrchestrationResult
    verification: VerificationResult | None = None
    product: DeliveredProduct | None = None


class Orchestrator:
    """Coordinate deterministic Phase 3 boundaries without becoming an authority."""

    def __init__(self, execution: VerificationExecutionService | None = None) -> None:
        self._execution = execution or VerificationExecutionService()

    def run(
        self,
        request: OrchestrationRequest,
        *,
        dispatch: DispatchRecord,
        product: DeliveredProduct,
        cwd: str | Path,
        adapters: Iterable[CommandEvidenceAdapter],
    ) -> OrchestrationOutcome:
        """Run the lifecycle, repeating only an explicit, bounded retry policy.

        A retry always creates RETRYING -> DISPATCHED and starts another
        execution/evidence cycle. P3-20 remains the sole PASS/FAIL authority.
        """
        self._validate_dispatch(request, dispatch)
        self._validate_product(dispatch, product)
        adapter_list = tuple(adapters)
        if not adapter_list:
            raise OrchestrationError("At least one execution adapter is required")

        snapshot = OrchestrationSnapshot(request.orchestration_id, OrchestrationState.RECEIVED)
        snapshot = snapshot.transition(OrchestrationState.DISPATCHED).bind_dispatch(dispatch)
        snapshot = snapshot.transition(OrchestrationState.DELIVERED).bind_product(product)
        current_product = product
        last_verification: VerificationResult | None = None

        while True:
            try:
                delivered, verification = self._execution.execute(
                    dispatch, current_product, cwd=cwd, adapters=adapter_list
                )
            except VerificationExecutionError as exc:
                snapshot = snapshot.transition(OrchestrationState.EXECUTED, failure_reason=str(exc))
                snapshot = snapshot.transition(OrchestrationState.FAILED, failure_reason="EXECUTION_FAILURE")
                return OrchestrationOutcome(self._result(snapshot), last_verification, current_product)
            except Exception as exc:
                raise OrchestrationFailure("Unexpected orchestration infrastructure failure") from exc

            current_product = delivered
            last_verification = verification
            snapshot = snapshot.transition(OrchestrationState.EXECUTED).bind_product(delivered)
            snapshot = snapshot.bind_verification(verification)
            snapshot = snapshot.transition(OrchestrationState.VERIFIED)

            if verification.status == "PASS":
                snapshot = snapshot.transition(OrchestrationState.COMPLETED)
                return OrchestrationOutcome(self._result(snapshot), verification, delivered)

            if not request.policy.can_retry("VERIFICATION_FAIL", snapshot.attempt):
                if request.policy.max_attempts > 1 and snapshot.attempt >= request.policy.max_attempts:
                    snapshot = snapshot.transition(OrchestrationState.ESCALATED, failure_reason="POLICY_EXHAUSTED")
                else:
                    snapshot = snapshot.transition(OrchestrationState.FAILED, failure_reason="VERIFICATION_FAIL")
                return OrchestrationOutcome(self._result(snapshot), verification, delivered)

            snapshot = snapshot.transition(OrchestrationState.RETRYING, failure_reason="VERIFICATION_FAIL")
            snapshot = snapshot.transition(OrchestrationState.DISPATCHED)
            snapshot = snapshot.transition(OrchestrationState.DELIVERED).bind_product(current_product)

    @staticmethod
    def _validate_dispatch(request: OrchestrationRequest, dispatch: DispatchRecord) -> None:
        checks = (
            (dispatch.task_id == request.task_id, "Dispatch task_id mismatch"),
            (dispatch.task_fingerprint == request.task_fingerprint, "Dispatch task fingerprint mismatch"),
            (dispatch.package_id == request.package_id, "Dispatch package_id mismatch"),
            (dispatch.package_fingerprint == request.package_fingerprint, "Dispatch package fingerprint mismatch"),
            (dispatch.selected_role == request.selected_role, "Dispatch role mismatch"),
        )
        for valid, message in checks:
            if not valid:
                raise OrchestrationError(message)

    @staticmethod
    def _validate_product(dispatch: DispatchRecord, product: DeliveredProduct) -> None:
        if not product.output_names:
            raise OrchestrationError("Delivered product must declare outputs")
        if not all(output in dispatch.permitted_outputs for output in product.output_names):
            raise OrchestrationError("Delivered product contains outputs outside the dispatch contract")

    @staticmethod
    def _result(snapshot: OrchestrationSnapshot) -> OrchestrationResult:
        return OrchestrationResult(
            orchestration_id=snapshot.orchestration_id,
            final_state=snapshot.state,
            attempt=snapshot.attempt,
            dispatch_fingerprint=snapshot.dispatch_fingerprint,
            artifact_fingerprint=snapshot.artifact_fingerprint,
            verification_fingerprint=snapshot.verification_fingerprint,
            failure_reason=snapshot.failure_reason,
        )
