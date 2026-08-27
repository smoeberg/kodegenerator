"""Idempotent AI-4 failure ingestion at the Council/Anti-Tube boundary."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.adaptation.anti_tube import AntiTubeTrigger
from phase4.adaptation.models import (
    AdaptationAction,
    AdaptationResult,
    ExecutionFailure,
    StrategyFingerprint,
)

from .persistence_models import (
    CouncilFailureObservationModel,
    CouncilOutboxEventModel,
    CouncilSessionModel,
)
from .runtime_models import (
    CouncilRuntimeEventType,
    CouncilSessionBinding,
    ExecutionFailedEvent,
)

if TYPE_CHECKING:
    from phase4.execution.models import ExecutionResult


class CouncilEventBindingError(RuntimeError):
    """Raised when an execution event is not bound to the stored aggregate."""


class CouncilFailureEventHandler:
    """Persist execution failures and derive Anti-Tube actions exactly once.

    The observation and its outbox event are committed atomically. Re-delivery
    of the same event returns the persisted result without incrementing failure
    history or emitting a second event.
    """

    _EVENT_BY_ACTION: ClassVar[dict[AdaptationAction, CouncilRuntimeEventType]] = {
        AdaptationAction.RETRY: CouncilRuntimeEventType.FAILURE_OBSERVED,
        AdaptationAction.PIVOT_REQUEST: CouncilRuntimeEventType.PIVOT_REQUIRED,
        AdaptationAction.HALT_ENVIRONMENT: (
            CouncilRuntimeEventType.ENVIRONMENT_HALT_REQUIRED
        ),
        AdaptationAction.POLICY_ESCALATION: (
            CouncilRuntimeEventType.POLICY_ESCALATION_REQUIRED
        ),
    }

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        same_failure_threshold: int = 2,
    ) -> None:
        if same_failure_threshold < 2:
            raise ValueError("same_failure_threshold must be at least 2")
        self.session_factory = session_factory
        self.same_failure_threshold = same_failure_threshold

    def handle(self, event: ExecutionFailedEvent) -> AdaptationResult:
        with self.session_factory() as db:
            existing = self._existing_result(db, event)
            if existing is not None:
                return existing

            session_row = db.scalar(
                select(CouncilSessionModel)
                .where(
                    CouncilSessionModel.organization_id == event.organization_id,
                    CouncilSessionModel.session_id == event.session_id,
                )
                .with_for_update()
            )
            if session_row is None:
                raise CouncilEventBindingError("council session not found")
            self._verify_binding(session_row, event)

            prior_rows = db.scalars(
                select(CouncilFailureObservationModel)
                .where(
                    CouncilFailureObservationModel.organization_id
                    == event.organization_id,
                    CouncilFailureObservationModel.session_id == event.session_id,
                    CouncilFailureObservationModel.fingerprint_hash
                    == event.fingerprint.summary_hash,
                )
                .order_by(
                    CouncilFailureObservationModel.created_at,
                    CouncilFailureObservationModel.event_id,
                )
            ).all()
            trigger = AntiTubeTrigger(
                same_failure_threshold=self.same_failure_threshold
            )
            for prior in prior_rows:
                trigger.evaluate_failure(
                    event.fingerprint,
                    ExecutionFailure.model_validate(prior.failure),
                )
            result = trigger.evaluate_failure(event.fingerprint, event.failure)

            db.add(
                CouncilFailureObservationModel(
                    event_id=event.event_id,
                    organization_id=event.organization_id,
                    session_id=event.session_id,
                    hypothesis_id=event.hypothesis_id,
                    execution_id=event.execution_id,
                    fingerprint_hash=event.fingerprint.summary_hash,
                    failure=event.failure.model_dump(mode="json"),
                    result=result.model_dump(mode="json"),
                    created_at=datetime.now(timezone.utc),
                )
            )
            event_type = self._EVENT_BY_ACTION[result.action]
            db.add(
                CouncilOutboxEventModel(
                    event_id=self._outbox_id(event.event_id, event_type),
                    organization_id=event.organization_id,
                    event_type=event_type.value,
                    aggregate_id=event.session_id,
                    payload={
                        "source_event_id": event.event_id,
                        "session_id": event.session_id,
                        "hypothesis_id": event.hypothesis_id,
                        "hypothesis_revision": event.hypothesis_revision,
                        "workspace_revision": event.workspace_revision,
                        "context_packet_id": event.context_packet_id,
                        "execution_id": event.execution_id,
                        "fingerprint_hash": event.fingerprint.summary_hash,
                        "adaptation": result.model_dump(mode="json"),
                    },
                    correlation_id=event.correlation_id or event.execution_id,
                    status="pending",
                    created_at=datetime.now(timezone.utc),
                    published_at=None,
                )
            )
            try:
                db.commit()
            except IntegrityError:
                # Another consumer may have committed the same event first.
                db.rollback()
                existing = self._existing_result(db, event)
                if existing is not None:
                    return existing
                raise
            return result

    @staticmethod
    def _verify_binding(
        session_row: CouncilSessionModel,
        event: ExecutionFailedEvent,
    ) -> None:
        expected = (
            session_row.hypothesis_id,
            session_row.hypothesis_revision,
            session_row.workspace_revision,
            session_row.context_packet_id,
        )
        actual = (
            event.hypothesis_id,
            event.hypothesis_revision,
            event.workspace_revision,
            event.context_packet_id,
        )
        if actual != expected:
            raise CouncilEventBindingError(
                "execution failure provenance does not match the council session"
            )

    @staticmethod
    def _existing_result(
        db: Session,
        event: ExecutionFailedEvent,
    ) -> AdaptationResult | None:
        row = db.scalar(
            select(CouncilFailureObservationModel).where(
                CouncilFailureObservationModel.organization_id == event.organization_id,
                CouncilFailureObservationModel.event_id == event.event_id,
            )
        )
        if row is None:
            row = db.scalar(
                select(CouncilFailureObservationModel).where(
                    CouncilFailureObservationModel.organization_id
                    == event.organization_id,
                    CouncilFailureObservationModel.execution_id == event.execution_id,
                )
            )
            if row is None:
                return None
            raise CouncilEventBindingError(
                "execution ID was already observed with different event content"
            )
        return AdaptationResult.model_validate(row.result)

    @staticmethod
    def _outbox_id(
        source_event_id: str,
        event_type: CouncilRuntimeEventType,
    ) -> str:
        return hashlib.sha256(
            f"{source_event_id}\x1f{event_type.value}".encode()
        ).hexdigest()


def execution_failure_event_from_result(
    result: ExecutionResult,
    *,
    binding: CouncilSessionBinding,
    session_id: str,
    hypothesis_id: str,
    fingerprint: StrategyFingerprint,
    task_id: str,
    correlation_id: str | None = None,
) -> ExecutionFailedEvent:
    """Translate one terminal AI-4 failure into the canonical Council event."""
    from phase4.execution.models import ExecutionStatus

    if result.status is not ExecutionStatus.FAILED:
        raise ValueError("only FAILED execution results can become failure events")
    if result.context_packet_id != binding.context_packet_id:
        raise CouncilEventBindingError(
            "execution result context packet does not match council binding"
        )
    failure = ExecutionFailure(
        failure_id=result.execution_id,
        task_id=task_id,
        error_type="execution_failed",
        error_message=result.error or "execution failed without an error message",
        metadata={
            "request_id": result.request_id,
            "adapter_id": result.adapter_id,
            "authority_policy_id": result.authority_policy_id,
            "authority_policy_version": result.authority_policy_version,
        },
    )
    return ExecutionFailedEvent.create(
        organization_id=binding.organization_id,
        session_id=session_id,
        hypothesis_id=hypothesis_id,
        hypothesis_revision=binding.hypothesis_revision,
        workspace_revision=binding.workspace_revision,
        context_packet_id=binding.context_packet_id,
        execution_id=result.execution_id,
        fingerprint=fingerprint,
        failure=failure,
        correlation_id=correlation_id,
    )
