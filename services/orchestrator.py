"""P3-22 deterministic lifecycle orchestrator.

This layer coordinates P3-19 dispatch, specialist delivery, P3-21 execution,
and the P3-20 verification authority. It never interprets or overrides the
verification decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

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
    """Raised only for infrastructure or orchestration contract failures."""


@dataclass(frozen=True)
class OrchestrationOutcome:
    result: OrchestrationResult
    verification: VerificationResult | None = None
    product: DeliveredProduct | None = None


class Orchestrator:
    """Coordinate the deterministic Phase 3 boundaries without becoming an authority."""

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
        self._validate_dispatch(request, dispatch)
        self._validate_product(dispatch, product)

        snapshot = OrchestrationSnapshot(request.orchestration_id, OrchestrationState.RECEIVED)
        snapshot = snapshot.transition(OrchestrationState.DISPATCHED).bind_dispatch(dispatch)
        snapshot = snapshot.transition(OrchestrationState.DELIVERED).bind_product(product)

        try:
            delivered, verification = self._execution.execute(
                dispatch, product, cwd=cwd, adapters=adapters
            )
        except VerificationExecutionError as exc:
            snapshot = snapshot.transition(OrchestrationState.EXECUTED, failure_reason=str(exc))
            snapshot = snapshot.transition(OrchestrationState.FAILED, failure_reason="EXECUTION_FAILURE")
            return OrchestrationOutcome(self._result(snapshot))
        except Exception as exc:
            raise OrchestrationFailure("Unexpected orchestration infrastructure failure") from exc

        snapshot = snapshot.transition(OrchestrationState.EXECUTED).bind_product(delivered)
        snapshot = snapshot.transition(OrchestrationState.VERIFIED).bind_verification(verification)

        if verification.status == "PASS":
            snapshot = snapshot.transition(OrchestrationState.COMPLETED)
        else:
            snapshot = self._handle_verification_failure(snapshot, request, "VERIFICATION_FAIL")

        return OrchestrationOutcome(self._result(snapshot), verification, delivered)

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
    def _handle_verification_failure(
        snapshot: OrchestrationSnapshot,
        request: OrchestrationRequest,
        failure: str,
    ) -> OrchestrationSnapshot:
        if request.policy.can_retry(failure, snapshot.attempt):
            return snapshot.transition(OrchestrationState.RETRYING, failure_reason=failure)
        if request.policy.max_attempts > 1 and snapshot.attempt >= request.policy.max_attempts:
            return snapshot.transition(OrchestrationState.ESCALATED, failure_reason="POLICY_EXHAUSTED")
        return snapshot.transition(OrchestrationState.FAILED, failure_reason=failure)

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
