"""Atomic WorkUnit claim boundary for Work Queue v0 (WQ-104).

This runtime executes the minimal atomic claim:

    claim_next_ready(worker_id, capabilities)

A single database transaction compare-and-sets one claimable PENDING work unit to
CLAIMED (with worker ownership, a fresh lease, and the exact approved dependency
snapshot) and appends one provenance revision in the same commit.

It deliberately does NOT implement scheduling, lease recovery, heartbeats,
review, rework, or dispatch. See WQ-105 / WQ-106 / WQ-107.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from domain.capability import Capability
from domain.work_queue import (
    DependencyVersionBinding,
    WorkerLease,
    WorkUnit,
    WorkUnitState,
)
from domain.work_queue_readiness import is_ready, is_worker_eligible
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.work_queue_models import WorkUnitModel
from infrastructure.persistence.work_queue_repository import WorkUnitRepository


class WorkUnitClaimError(RuntimeError):
    """Raised when an atomic claim transaction cannot complete."""


class WorkQueueClaimService:
    """Organization-scoped minimal atomic claim service."""

    def __init__(
        self,
        session_factory,
        *,
        organization_id: str,
        lease_seconds: int = 60,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        organization_id = organization_id.strip()
        if not organization_id or len(organization_id) > 128:
            raise ValueError("organization_id must contain 1-128 characters")
        self.session_factory = session_factory
        self.organization_id = organization_id
        self.lease_seconds = lease_seconds

    def claim_next_ready(
        self, worker_id: str, capabilities: Iterable[Capability]
    ) -> WorkUnit | None:
        """Atomically claim the next ready work unit for ``worker_id``.

        Returns the claimed ``WorkUnit`` or ``None`` when nothing is currently
        claimable for this worker. Uses a compare-and-set so that exactly one
        worker ever obtains ownership of a given work unit, even where
        ``SELECT ... FOR UPDATE`` is ignored (e.g. SQLite).
        """
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        capabilities = list(capabilities)
        for _ in range(100):
            with self.session_factory() as session:
                apply_tenant_context(session, self.organization_id)
                claimed, contested = self._claim_in_session(
                    session, worker_id, capabilities
                )
                if claimed is not None:
                    session.commit()
                    return claimed
                session.rollback()
                if not contested:
                    # Nothing is even claimable right now; do not burn retries or
                    # force a fabricated contention error.
                    return None
        raise WorkUnitClaimError("claim contention exceeded retry limit")

    def claim_ready(
        self,
        work_unit_id: str,
        worker_id: str,
        capabilities: Iterable[Capability],
    ) -> WorkUnit | None:
        """Atomically claim one exact ready WorkUnit without touching its peers."""
        if not isinstance(work_unit_id, str) or not work_unit_id.strip():
            raise ValueError("work_unit_id must be non-empty")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        capabilities = list(capabilities)
        for _ in range(100):
            with self.session_factory() as session:
                apply_tenant_context(session, self.organization_id)
                candidates = [
                    model
                    for model in self._pending_candidates(session)
                    if model.work_unit_id == work_unit_id
                ]
                if not candidates:
                    session.rollback()
                    return None
                candidate = WorkUnitRepository._from_model(candidates[0])
                if not is_worker_eligible(candidate, capabilities):
                    session.rollback()
                    return None
                dependencies = self._load_dependencies(session, candidate)
                if not is_ready(candidate, dependencies):
                    session.rollback()
                    return None
                snapshot = self._approved_snapshot(candidate, dependencies)
                if snapshot is None:
                    session.rollback()
                    return None
                claimed = self._cas_claim(session, candidate, worker_id, snapshot)
                if claimed is not None:
                    session.commit()
                    return claimed
                session.rollback()
        raise WorkUnitClaimError("claim contention exceeded retry limit")

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #

    def _claim_in_session(
        self, session: Session, worker_id: str, capabilities: list[Capability]
    ) -> tuple[WorkUnit | None, bool]:
        candidates = self._pending_candidates(session)
        contested = False
        for model in candidates:
            candidate = WorkUnitRepository._from_model(model)
            if not is_worker_eligible(candidate, capabilities):
                continue
            dependencies = self._load_dependencies(session, candidate)
            if not is_ready(candidate, dependencies):
                continue
            snapshot = self._approved_snapshot(candidate, dependencies)
            if snapshot is None:
                continue
            claimed = self._cas_claim(session, candidate, worker_id, snapshot)
            if claimed is None:
                contested = True
                continue
            return claimed, False
        return None, contested

    def _pending_candidates(self, session: Session) -> list:
        stmt = (
            select(WorkUnitModel)
            .where(
                WorkUnitModel.organization_id == self.organization_id,
                WorkUnitModel.state == WorkUnitState.PENDING.name,
            )
            .order_by(WorkUnitModel.created_at, WorkUnitModel.work_unit_id)
        )
        return list(session.scalars(stmt).all())

    def _load_dependencies(self, session: Session, candidate: WorkUnit) -> dict:
        if not candidate.depends_on:
            return {}
        stmt = select(WorkUnitModel).where(
            WorkUnitModel.organization_id == self.organization_id,
            WorkUnitModel.work_unit_id.in_(candidate.depends_on),
        )
        models = session.scalars(stmt).all()
        return {
            model.work_unit_id: WorkUnitRepository._from_model(model)
            for model in models
        }

    def _approved_snapshot(
        self, candidate: WorkUnit, dependencies: dict
    ) -> tuple[DependencyVersionBinding, ...] | None:
        """Build the exact approved dependency snapshot in ``depends_on`` order.

        Returns ``None`` if any declared dependency is missing, misidentified,
        non-APPROVED, or lacks an immutable delivered artifact version.
        """
        bindings: list[DependencyVersionBinding] = []
        for dependency_id in candidate.depends_on:
            dependency = dependencies.get(dependency_id)
            if (
                dependency is None
                or dependency.id != dependency_id
                or dependency.state is not WorkUnitState.APPROVED
                or dependency.delivered_artifact_version is None
            ):
                return None
            bindings.append(
                DependencyVersionBinding(
                    work_unit_id=dependency.id,
                    version=dependency.delivered_artifact_version,
                )
            )
        return tuple(bindings)

    def _cas_claim(
        self,
        session: Session,
        candidate: WorkUnit,
        worker_id: str,
        snapshot: tuple[DependencyVersionBinding, ...],
    ) -> WorkUnit | None:
        now = datetime.now(timezone.utc)
        lease = WorkerLease(
            lease_id=str(uuid4()),
            worker_id=worker_id,
            claimed_at=now,
            expires_at=now + timedelta(seconds=self.lease_seconds),
        )
        lease_json = {
            "lease_id": lease.lease_id,
            "worker_id": lease.worker_id,
            "claimed_at": lease.claimed_at.isoformat(),
            "expires_at": lease.expires_at.isoformat(),
        }
        snapshot_json = [
            {
                "work_unit_id": binding.work_unit_id,
                "version": {
                    "kind": binding.version.kind,
                    "value": binding.version.value,
                },
            }
            for binding in snapshot
        ]
        result = session.execute(
            update(WorkUnitModel)
            .where(
                WorkUnitModel.organization_id == self.organization_id,
                WorkUnitModel.work_unit_id == candidate.id,
                WorkUnitModel.state == WorkUnitState.PENDING.name,
                WorkUnitModel.claimed_by.is_(None),
                WorkUnitModel.lease.is_(None),
            )
            .values(
                state=WorkUnitState.CLAIMED.name,
                claimed_by=worker_id,
                lease=lease_json,
                depends_on_snapshot=snapshot_json,
                updated_at=now,
            )
        )
        if result.rowcount != 1:
            # Lost the CAS to another claimant. No ownership, no revision.
            return None
        claimed = WorkUnit(
            id=candidate.id,
            title=candidate.title,
            required_capability=candidate.required_capability,
            state=WorkUnitState.CLAIMED,
            depends_on=candidate.depends_on,
            depends_on_snapshot=snapshot,
            base_version=candidate.base_version,
            allowed_resources=candidate.allowed_resources,
            acceptance_refs=candidate.acceptance_refs,
            delivered_artifact_version=candidate.delivered_artifact_version,
            claimed_by=worker_id,
            lease=lease,
            previous_worker=candidate.previous_worker,
            rework_attempts=candidate.rework_attempts,
            created_at=candidate.created_at,
            updated_at=now,
        )
        repo = WorkUnitRepository(session)
        repo.append_revision(self.organization_id, claimed)
        session.flush()
        return claimed


__all__ = ["WorkQueueClaimService", "WorkUnitClaimError"]
