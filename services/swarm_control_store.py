"""Persistence boundary for tenant-scoped Swarm project and dispatch state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.models import ProjectModel
from infrastructure.persistence.swarm_control_models import (
    SwarmDispatchControlModel,
    SwarmProjectDispatchModel,
)


class SwarmProjectConflictError(RuntimeError):
    """A dispatch registration conflicts with immutable existing state."""


@dataclass(frozen=True)
class SwarmProjectDispatch:
    organization_id: str
    project_id: str
    owner_id: str
    requirements: dict[str, Any]
    created_at: datetime
    revision: int


class SwarmControlStore:
    def __init__(self, session_factory) -> None:
        self._sessions = session_factory

    def register_project(
        self,
        *,
        organization_id: str,
        project_id: str,
        owner_id: str,
        requirements: dict[str, Any],
    ) -> tuple[SwarmProjectDispatch, bool]:
        now = datetime.now(timezone.utc)
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            project = session.scalar(
                select(ProjectModel).where(
                    ProjectModel.organization_id == organization_id,
                    ProjectModel.id == project_id,
                    ProjectModel.created_by == owner_id,
                )
            )
            if project is None:
                raise KeyError(project_id)
            existing = session.get(
                SwarmProjectDispatchModel, (organization_id, project_id)
            )
            if existing is not None:
                dispatch = self._dispatch(existing)
                if (
                    dispatch.owner_id != owner_id
                    or dispatch.requirements != requirements
                ):
                    raise SwarmProjectConflictError(
                        "project dispatch already exists with different immutable state"
                    )
                return dispatch, False
            row = SwarmProjectDispatchModel(
                organization_id=organization_id,
                project_id=project_id,
                owner_id=owner_id,
                requirements=requirements,
                created_at=now,
                updated_at=now,
                revision=0,
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return self.register_project(
                    organization_id=organization_id,
                    project_id=project_id,
                    owner_id=owner_id,
                    requirements=requirements,
                )
            return self._dispatch(row), True

    def get_project(
        self, organization_id: str, project_id: str
    ) -> SwarmProjectDispatch | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(SwarmProjectDispatchModel, (organization_id, project_id))
            return self._dispatch(row) if row is not None else None

    def require_owner(
        self, organization_id: str, project_id: str, owner_id: str
    ) -> SwarmProjectDispatch:
        dispatch = self.get_project(organization_id, project_id)
        if dispatch is None:
            raise KeyError(project_id)
        if dispatch.owner_id != owner_id:
            raise PermissionError("project access denied")
        return dispatch

    def is_paused(self, organization_id: str) -> bool:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(SwarmDispatchControlModel, organization_id)
            return bool(row and row.paused)

    def set_paused(self, organization_id: str, *, paused: bool, actor_id: str) -> bool:
        now = datetime.now(timezone.utc)
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(SwarmDispatchControlModel, organization_id)
            if row is None:
                row = SwarmDispatchControlModel(
                    organization_id=organization_id,
                    paused=paused,
                    updated_by=actor_id,
                    updated_at=now,
                    revision=0,
                )
                session.add(row)
            else:
                row.paused = paused
                row.updated_by = actor_id
                row.updated_at = now
                row.revision += 1
            session.commit()
            return row.paused

    @staticmethod
    def _dispatch(row: SwarmProjectDispatchModel) -> SwarmProjectDispatch:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return SwarmProjectDispatch(
            organization_id=row.organization_id,
            project_id=row.project_id,
            owner_id=row.owner_id,
            requirements=dict(row.requirements),
            created_at=created_at,
            revision=row.revision,
        )
