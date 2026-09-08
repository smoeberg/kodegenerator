"""SC-101C project-scope binding and cooperative Work Queue supersession.

The active Project aggregate remains the authority for which plan is executable.
This module binds WorkUnits to one project + plan using canonical immutable
acceptance references, filters claims to the current scope, and best-effort
fences already-claimed work when a newer plan supersedes it.

Cancellation is cooperative: it is useful for stopping wasted work, but system
correctness still relies on the SC-101B apply/certification stale-scope gates.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import select

from domain.capability import Capability
from domain.project import ProjectStatus
from domain.work_queue import WorkUnit, WorkUnitContractError, WorkUnitState
from domain.work_queue_readiness import is_worker_eligible
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.project_scope_repository import ProjectScopeRepository
from infrastructure.persistence.work_queue_models import WorkUnitModel
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue import WorkQueueClaimService
from infrastructure.runtime.work_queue_lease import WorkQueueLeaseError, WorkQueueLeaseService

_PROJECT_REF_PREFIX = "project_scope:project:"
_PLAN_REF_PREFIX = "project_scope:plan:"
ScopeValidator = Callable[[str, str, str], bool]


def _canonical_text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WorkUnitContractError(f"{name} must be canonical non-empty text")
    if len(value) > 128:
        raise WorkUnitContractError(f"{name} exceeds 128 characters")
    return value


def _plan_fingerprint(value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise WorkUnitContractError("plan_request_fingerprint must be lowercase SHA-256")
    return value


def bind_work_unit_scope(
    work_unit: WorkUnit,
    *,
    project_id: str,
    plan_request_fingerprint: str,
) -> WorkUnit:
    """Return ``work_unit`` hard-bound to one immutable project + plan scope.

    Rebinding is fail-closed. Re-applying the exact same binding is idempotent.
    """
    project_id = _canonical_text(project_id, "project_id")
    plan_request_fingerprint = _plan_fingerprint(plan_request_fingerprint)
    existing = work_unit_scope(work_unit)
    requested = (project_id, plan_request_fingerprint)
    if existing is not None and existing != requested:
        raise WorkUnitContractError("WorkUnit project scope is immutable")
    if existing == requested:
        return work_unit
    refs = work_unit.acceptance_refs + (
        f"{_PROJECT_REF_PREFIX}{project_id}",
        f"{_PLAN_REF_PREFIX}{plan_request_fingerprint}",
    )
    return replace(work_unit, acceptance_refs=refs)


def work_unit_scope(work_unit: WorkUnit) -> Optional[tuple[str, str]]:
    """Read the canonical project + plan binding from a WorkUnit."""
    project_refs = [
        value[len(_PROJECT_REF_PREFIX) :]
        for value in work_unit.acceptance_refs
        if value.startswith(_PROJECT_REF_PREFIX)
    ]
    plan_refs = [
        value[len(_PLAN_REF_PREFIX) :]
        for value in work_unit.acceptance_refs
        if value.startswith(_PLAN_REF_PREFIX)
    ]
    if not project_refs and not plan_refs:
        return None
    if len(project_refs) != 1 or len(plan_refs) != 1:
        raise WorkUnitContractError("WorkUnit has malformed project scope binding")
    return (
        _canonical_text(project_refs[0], "project_id"),
        _plan_fingerprint(plan_refs[0]),
    )


def database_scope_validator(database) -> ScopeValidator:
    """Build a trusted validator backed by the current Project aggregate."""

    def validate(
        organization_id: str,
        project_id: str,
        plan_request_fingerprint: str,
    ) -> bool:
        try:
            with database.session(organization_id) as session:
                project = ProjectScopeRepository(session).get_for_organization(
                    project_id,
                    organization_id,
                )
        except Exception:
            return False
        return bool(
            project is not None
            and project.status is ProjectStatus.ACTIVE
            and project.active_plan_request_fingerprint == plan_request_fingerprint
        )

    return validate


class ProjectScopedWorkQueueClaimService(WorkQueueClaimService):
    """Claim only WorkUnits bound to one currently-active project + plan."""

    def __init__(
        self,
        session_factory,
        *,
        organization_id: str,
        project_id: str,
        plan_request_fingerprint: str,
        scope_validator: ScopeValidator,
        lease_seconds: int = 60,
    ) -> None:
        super().__init__(
            session_factory,
            organization_id=organization_id,
            lease_seconds=lease_seconds,
        )
        self.project_id = _canonical_text(project_id, "project_id")
        self.plan_request_fingerprint = _plan_fingerprint(plan_request_fingerprint)
        if not callable(scope_validator):
            raise TypeError("scope_validator must be callable")
        self.scope_validator = scope_validator

    def _scope_is_current(self) -> bool:
        try:
            return bool(
                self.scope_validator(
                    self.organization_id,
                    self.project_id,
                    self.plan_request_fingerprint,
                )
            )
        except Exception:
            return False

    def _pending_candidates(self, session):
        if not self._scope_is_current():
            return []
        candidates = super()._pending_candidates(session)
        scoped = []
        for model in candidates:
            try:
                binding = work_unit_scope(WorkUnitRepository._from_model(model))
            except WorkUnitContractError:
                continue
            if binding == (self.project_id, self.plan_request_fingerprint):
                scoped.append(model)
        return scoped


class ProjectScopedWorkQueueLeaseService(WorkQueueLeaseService):
    """Fence lease operations once the WorkUnit's plan is superseded."""

    def __init__(
        self,
        session_factory,
        *,
        organization_id: str,
        project_id: str,
        plan_request_fingerprint: str,
        scope_validator: ScopeValidator,
        lease_seconds: int = 60,
        clock=None,
    ) -> None:
        super().__init__(
            session_factory,
            organization_id=organization_id,
            lease_seconds=lease_seconds,
            clock=clock,
        )
        self.project_id = _canonical_text(project_id, "project_id")
        self.plan_request_fingerprint = _plan_fingerprint(plan_request_fingerprint)
        if not callable(scope_validator):
            raise TypeError("scope_validator must be callable")
        self.scope_validator = scope_validator

    def _scope_is_current(self) -> bool:
        try:
            return bool(
                self.scope_validator(
                    self.organization_id,
                    self.project_id,
                    self.plan_request_fingerprint,
                )
            )
        except Exception:
            return False

    def heartbeat(self, work_unit_id: str, *, worker_id: str, lease_id: str):
        if not self._scope_is_current():
            return None
        return super().heartbeat(work_unit_id, worker_id=worker_id, lease_id=lease_id)

    def submit_for_review(
        self,
        work_unit_id: str,
        *,
        worker_id: str,
        lease_id: str,
        delivered_artifact_version,
    ):
        if not self._scope_is_current():
            return None
        return super().submit_for_review(
            work_unit_id,
            worker_id=worker_id,
            lease_id=lease_id,
            delivered_artifact_version=delivered_artifact_version,
        )

    def recover_next_expired(
        self,
        worker_id: str,
        capabilities: Iterable[Capability],
    ) -> Optional[WorkUnit]:
        """Recover only expired work already bound to this exact active scope."""
        self._identity(worker_id, "worker_id")
        if not self._scope_is_current():
            return None
        capabilities = list(capabilities)
        for _ in range(100):
            with self.session_factory() as session:
                apply_tenant_context(session, self.organization_id)
                now = self.clock()
                if (
                    not isinstance(now, datetime)
                    or now.tzinfo is None
                    or now.utcoffset() is None
                ):
                    raise ValueError("clock must return a timezone-aware datetime")
                now = now.astimezone(timezone.utc)
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
                    try:
                        binding = work_unit_scope(candidate)
                    except WorkUnitContractError:
                        continue
                    lease = candidate.lease
                    if (
                        binding != (self.project_id, self.plan_request_fingerprint)
                        or lease is None
                        or lease.expires_at > now
                        or not is_worker_eligible(candidate, capabilities)
                    ):
                        continue
                    recovered = self._recover_one(
                        session,
                        model,
                        candidate,
                        worker_id,
                        now,
                    )
                    if recovered is None:
                        contested = True
                        continue
                    session.commit()
                    return recovered
                session.rollback()
                if not contested:
                    return None
        raise WorkQueueLeaseError("lease recovery contention exceeded retry limit")


def request_superseded_scope_cancellation(
    database,
    *,
    organization_id: str,
    project_id: str,
    active_plan_request_fingerprint: str,
) -> int:
    """Best-effort fence claimed work from superseded plans.

    A stale CLAIMED unit becomes FAILED and loses its lease, so an in-flight
    worker can no longer heartbeat or submit through the existing fenced lease
    boundary. Pending stale units remain historical but are not claimable by
    ``ProjectScopedWorkQueueClaimService``.
    """
    project_id = _canonical_text(project_id, "project_id")
    active_plan_request_fingerprint = _plan_fingerprint(active_plan_request_fingerprint)
    now = datetime.now(timezone.utc)
    changed = 0
    with database.session(organization_id) as session:
        repository = WorkUnitRepository(session)
        for work_unit in repository.list_for_organization(organization_id):
            try:
                binding = work_unit_scope(work_unit)
            except WorkUnitContractError:
                continue
            if binding is None:
                continue
            bound_project, bound_plan = binding
            if (
                bound_project != project_id
                or bound_plan == active_plan_request_fingerprint
                or work_unit.state is not WorkUnitState.CLAIMED
            ):
                continue
            cancelled = replace(
                work_unit,
                state=WorkUnitState.FAILED,
                previous_worker=work_unit.claimed_by,
                claimed_by=None,
                lease=None,
                updated_at=now,
            )
            repository.update(organization_id, cancelled)
            changed += 1
        session.commit()
    return changed


__all__ = [
    "ProjectScopedWorkQueueClaimService",
    "ProjectScopedWorkQueueLeaseService",
    "bind_work_unit_scope",
    "database_scope_validator",
    "request_superseded_scope_cancellation",
    "work_unit_scope",
]
