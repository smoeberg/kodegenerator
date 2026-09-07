"""WQ-105 lease renewal, expiry recovery, and fenced submission for Work Queue v0.

The service extends WQ-104 ownership semantics without introducing a scheduler:

- active leases cannot be stolen;
- only an expired CLAIMED WorkUnit can be recovered;
- recovery uses compare-and-set and creates a fresh lease token;
- stale lease tokens cannot heartbeat or submit;
- successful transitions append exactly one WorkUnit revision in the same transaction.
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


class WorkQueueLeaseError(RuntimeError):
    """Raised when lease recovery cannot make forward progress under contention."""


def _lease_payload(lease: WorkerLease) -> dict:
    return {
        "lease_id": lease.lease_id,
        "worker_id": lease.worker_id,
        "claimed_at": lease.claimed_at.isoformat(),
        "expires_at": lease.expires_at.isoformat(),
    }


def _version_payload(version: ImmutableVersionRef) -> dict:
    return {"kind": version.kind, "value": version.value}


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("clock must return a timezone-aware datetime")
    return value.astimezone(timezone.utc)


class WorkQueueLeaseService:
    """Organization-scoped lease lifecycle boundary for CLAIMED WorkUnits."""

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

    def heartbeat(
        self,
        work_unit_id: str,
        *,
        worker_id: str,
        lease_id: str,
    ) -> Optional[WorkUnit]:
        """Extend one still-active lease without changing its fencing token."""
        self._identity(work_unit_id, "work_unit_id")
        self._identity(worker_id, "worker_id")
        self._identity(lease_id, "lease_id")
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            model = session.get(WorkUnitModel, (self.organization_id, work_unit_id))
            if model is None:
                return None
            candidate = WorkUnitRepository._from_model(model)
            now = _utc(self.clock())
            lease = candidate.lease
            if (
                candidate.state is not WorkUnitState.CLAIMED
                or candidate.claimed_by != worker_id
                or lease is None
                or lease.worker_id != worker_id
                or lease.lease_id != lease_id
                or lease.expires_at <= now
            ):
                return None

            renewed = WorkerLease(
                lease_id=lease.lease_id,
                worker_id=worker_id,
                claimed_at=lease.claimed_at,
                expires_at=now + timedelta(seconds=self.lease_seconds),
            )
            updated = replace(candidate, lease=renewed, updated_at=now)
            if not self._cas_projection(
                session,
                model,
                values={"lease": _lease_payload(renewed), "updated_at": now},
            ):
                session.rollback()
                return None
            WorkUnitRepository(session).append_revision(self.organization_id, updated)
            session.commit()
            return updated

    def recover_next_expired(
        self,
        worker_id: str,
        capabilities: Iterable[Capability],
    ) -> Optional[WorkUnit]:
        """Atomically recover the next expired compatible CLAIMED WorkUnit.

        Active leases are skipped.  Recovery allocates a new fencing token and
        preserves the previous owner in ``previous_worker``.
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
                        WorkUnitModel.state == WorkUnitState.CLAIMED.name,
                    )
                    .order_by(WorkUnitModel.updated_at, WorkUnitModel.work_unit_id)
                )
                for model in session.scalars(stmt).all():
                    candidate = WorkUnitRepository._from_model(model)
                    lease = candidate.lease
                    if (
                        lease is None
                        or lease.expires_at > now
                        or not is_worker_eligible(candidate, capabilities)
                    ):
                        continue
                    recovered = self._recover_one(session, model, candidate, worker_id, now)
                    if recovered is None:
                        contested = True
                        continue
                    session.commit()
                    return recovered
                session.rollback()
                if not contested:
                    return None
        raise WorkQueueLeaseError("lease recovery contention exceeded retry limit")

    def submit_for_review(
        self,
        work_unit_id: str,
        *,
        worker_id: str,
        lease_id: str,
        delivered_artifact_version: ImmutableVersionRef,
    ) -> Optional[WorkUnit]:
        """Fence CLAIMED -> AWAITING_REVIEW by the exact active lease token."""
        self._identity(work_unit_id, "work_unit_id")
        self._identity(worker_id, "worker_id")
        self._identity(lease_id, "lease_id")
        if not isinstance(delivered_artifact_version, ImmutableVersionRef):
            raise TypeError("delivered_artifact_version must be an ImmutableVersionRef")

        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            model = session.get(WorkUnitModel, (self.organization_id, work_unit_id))
            if model is None:
                return None
            candidate = WorkUnitRepository._from_model(model)
            now = _utc(self.clock())
            lease = candidate.lease
            if (
                candidate.state is not WorkUnitState.CLAIMED
                or candidate.claimed_by != worker_id
                or lease is None
                or lease.worker_id != worker_id
                or lease.lease_id != lease_id
                or lease.expires_at <= now
            ):
                return None

            submitted = replace(
                candidate,
                state=WorkUnitState.AWAITING_REVIEW,
                delivered_artifact_version=delivered_artifact_version,
                previous_worker=worker_id,
                claimed_by=None,
                lease=None,
                updated_at=now,
            )
            if not self._cas_projection(
                session,
                model,
                values={
                    "state": WorkUnitState.AWAITING_REVIEW.name,
                    "delivered_artifact_version": _version_payload(delivered_artifact_version),
                    "previous_worker": worker_id,
                    "claimed_by": None,
                    "lease": null(),
                    "updated_at": now,
                },
            ):
                session.rollback()
                return None
            WorkUnitRepository(session).append_revision(self.organization_id, submitted)
            session.commit()
            return submitted

    def _recover_one(
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
        recovered = replace(
            candidate,
            claimed_by=worker_id,
            lease=lease,
            previous_worker=candidate.claimed_by,
            updated_at=now,
        )
        if not self._cas_projection(
            session,
            model,
            values={
                "claimed_by": worker_id,
                "lease": _lease_payload(lease),
                "previous_worker": candidate.claimed_by,
                "updated_at": now,
            },
        ):
            return None
        WorkUnitRepository(session).append_revision(self.organization_id, recovered)
        session.flush()
        return recovered

    def _cas_projection(self, session: Session, model: WorkUnitModel, *, values: dict) -> bool:
        """CAS by current projection version without relying on JSON equality."""
        result = session.execute(
            update(WorkUnitModel)
            .where(
                WorkUnitModel.organization_id == self.organization_id,
                WorkUnitModel.work_unit_id == model.work_unit_id,
                WorkUnitModel.state == model.state,
                WorkUnitModel.updated_at == model.updated_at,
            )
            .values(**values)
        )
        return result.rowcount == 1

    @staticmethod
    def _identity(value: str, field_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be non-empty")


__all__ = ["WorkQueueLeaseError", "WorkQueueLeaseService"]
