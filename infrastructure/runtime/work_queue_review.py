"""WQ-106 independent review and bounded rework transitions for Work Queue v0.

Review is a separate authority from worker execution.  Reviewer rejection is a
normal lifecycle event (REJECTED), never FAILED.  Rework claims are atomic,
preserve append-only history, clear the rejected artifact from the current
projection, and allocate a fresh lease so the next submission must carry a new
immutable artifact version.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from uuid import uuid4

from sqlalchemy import null, select, update
from sqlalchemy.orm import Session

from domain.capability import Capability
from domain.work_queue import ImmutableVersionRef, WorkUnit, WorkUnitState, WorkerLease
from domain.work_queue_readiness import is_worker_eligible
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.work_queue_models import WorkUnitModel
from infrastructure.persistence.work_queue_repository import WorkUnitRepository


class WorkQueueReviewError(RuntimeError):
    """Raised when review/rework contention cannot make forward progress."""


def _lease_payload(lease: WorkerLease) -> dict:
    return {
        "lease_id": lease.lease_id,
        "worker_id": lease.worker_id,
        "claimed_at": lease.claimed_at.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
    }


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class WorkQueueReviewService:
    """Organization-scoped review authority and atomic rework claim service."""

    def __init__(
        self,
        session_factory,
        *,
        organization_id: str,
        lease_seconds: int = 60,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if not isinstance(organization_id, str):
            raise ValueError("organization_id must be text")
        organization_id = organization_id.strip()
        if not organization_id or len(organization_id) > 128:
            raise ValueError("organization_id must contain 1-128 characters")
        self.session_factory = session_factory
        self.organization_id = organization_id
        self.lease_seconds = lease_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def approve(
        self,
        work_unit_id: str,
        *,
        reviewer_id: str,
        artifact_version: ImmutableVersionRef,
    ) -> Optional[WorkUnit]:
        """Approve the exact artifact currently awaiting review."""
        return self._review(
            work_unit_id,
            reviewer_id=reviewer_id,
            artifact_version=artifact_version,
            decision=WorkUnitState.APPROVED,
        )

    def reject(
        self,
        work_unit_id: str,
        *,
        reviewer_id: str,
        artifact_version: ImmutableVersionRef,
    ) -> Optional[WorkUnit]:
        """Reject the exact artifact without converting rejection to FAILED."""
        return self._review(
            work_unit_id,
            reviewer_id=reviewer_id,
            artifact_version=artifact_version,
            decision=WorkUnitState.REJECTED,
        )

    def claim_rework(
        self,
        worker_id: str,
        capabilities: Iterable[Capability],
        *,
        allow_preference_override: bool = False,
    ) -> Optional[WorkUnit]:
        """Atomically claim the next REJECTED compatible WorkUnit for rework.

        The first rework attempt is reserved for ``previous_worker`` by default.
        An orchestrator may explicitly override that preference when the prior
        worker is unavailable.  After the first bounded attempt, any compatible
        worker may claim.  Every successful rework claim gets a fresh lease and
        increments ``rework_attempts`` exactly once.
        """
        self._identity(worker_id, "worker_id")
        capabilities = list(capabilities)
        for _ in range(100):
            with self.session_factory() as session:
                apply_tenant_context(session, self.organization_id)
                now = _utc(self.clock())
                contested = False
                stmt = (
                    select(WorkUnitModel)
                    .where(
                        WorkUnitModel.organization_id == self.organization_id,
                        WorkUnitModel.state == WorkUnitState.REJECTED.name,
                    )
                    .order_by(WorkUnitModel.updated_at, WorkUnitModel.work_unit_id)
                )
                for model in session.scalars(stmt).all():
                    candidate = WorkUnitRepository._from_model(model)
                    if not is_worker_eligible(candidate, capabilities):
                        continue
                    if (
                        candidate.rework_attempts == 0
                        and candidate.previous_worker
                        and candidate.previous_worker != worker_id
                        and not allow_preference_override
                    ):
                        continue
                    claimed = self._claim_one(session, model, candidate, worker_id, now)
                    if claimed is None:
                        contested = True
                        continue
                    session.commit()
                    return claimed
                session.rollback()
                if not contested:
                    return None
        raise WorkQueueReviewError("rework claim contention exceeded retry limit")

    def _review(
        self,
        work_unit_id: str,
        *,
        reviewer_id: str,
        artifact_version: ImmutableVersionRef,
        decision: WorkUnitState,
    ) -> Optional[WorkUnit]:
        self._identity(work_unit_id, "work_unit_id")
        self._identity(reviewer_id, "reviewer_id")
        if not isinstance(artifact_version, ImmutableVersionRef):
            raise TypeError("artifact_version must be an ImmutableVersionRef")
        if decision not in (WorkUnitState.APPROVED, WorkUnitState.REJECTED):
            raise ValueError("review decision must be APPROVED or REJECTED")

        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            model = session.get(WorkUnitModel, (self.organization_id, work_unit_id))
            if model is None:
                return None
            candidate = WorkUnitRepository._from_model(model)
            if (
                candidate.state is not WorkUnitState.AWAITING_REVIEW
                or candidate.delivered_artifact_version != artifact_version
                or candidate.claimed_by is not None
                or candidate.lease is not None
            ):
                return None
            if candidate.previous_worker == reviewer_id:
                # Execution and review authority must remain separate.
                return None

            now = _utc(self.clock())
            reviewed = replace(candidate, state=decision, updated_at=now)
            result = session.execute(
                update(WorkUnitModel)
                .where(
                    WorkUnitModel.organization_id == self.organization_id,
                    WorkUnitModel.work_unit_id == work_unit_id,
                    WorkUnitModel.state == WorkUnitState.AWAITING_REVIEW.name,
                    WorkUnitModel.updated_at == model.updated_at,
                )
                .values(state=decision.name, updated_at=now)
            )
            if result.rowcount != 1:
                session.rollback()
                return None
            WorkUnitRepository(session).append_revision(self.organization_id, reviewed)
            session.commit()
            return reviewed

    def _claim_one(
        self,
        session: Session,
        model: WorkUnitModel,
        candidate: WorkUnit,
        worker_id: str,
        now: datetime,
    ) -> Optional[WorkUnit]:
        lease = WorkerLease(
            lease_id=str(uuid4()),
            worker_id=worker_id,
            claimed_at=now,
            expires_at=now + timedelta(seconds=self.lease_seconds),
        )
        claimed = replace(
            candidate,
            state=WorkUnitState.CLAIMED,
            claimed_by=worker_id,
            lease=lease,
            delivered_artifact_version=None,
            rework_attempts=candidate.rework_attempts + 1,
            updated_at=now,
        )
        result = session.execute(
            update(WorkUnitModel)
            .where(
                WorkUnitModel.organization_id == self.organization_id,
                WorkUnitModel.work_unit_id == candidate.id,
                WorkUnitModel.state == WorkUnitState.REJECTED.name,
                WorkUnitModel.updated_at == model.updated_at,
            )
            .values(
                state=WorkUnitState.CLAIMED.name,
                claimed_by=worker_id,
                lease=_lease_payload(lease),
                delivered_artifact_version=null(),
                rework_attempts=candidate.rework_attempts + 1,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            return None
        WorkUnitRepository(session).append_revision(self.organization_id, claimed)
        session.flush()
        return claimed

    @staticmethod
    def _identity(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be non-empty")


__all__ = ["WorkQueueReviewError", "WorkQueueReviewService"]
