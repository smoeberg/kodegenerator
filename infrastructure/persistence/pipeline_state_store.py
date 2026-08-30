"""SQLAlchemy-backed durable state for pipeline orchestration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .database import apply_tenant_context
from .models import PipelineRuntimeStateModel


class PipelineStateConflictError(RuntimeError):
    """A different worker persisted a newer state revision."""


class SQLAlchemyPipelineStateStore:
    """Persist pipeline snapshots with optimistic concurrency control."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        organization_id: str,
        store_id: str = "pipeline-default",
    ) -> None:
        if not organization_id.strip() or not store_id.strip():
            raise ValueError("organization_id and store_id are required")
        self._session_factory = session_factory
        self._organization_id = organization_id
        self._store_id = store_id
        self._revision: int | None = None

    def load(self) -> dict[str, Any] | None:
        with self._session_factory() as session:
            apply_tenant_context(session, self._organization_id)
            row = session.scalar(
                select(PipelineRuntimeStateModel).where(
                    PipelineRuntimeStateModel.store_id == self._store_id,
                    PipelineRuntimeStateModel.organization_id == self._organization_id,
                )
            )
            if row is None:
                self._revision = None
                return None
            self._revision = row.revision
            return dict(row.snapshot)

    def save(self, snapshot: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        with self._session_factory() as session, session.begin():
            apply_tenant_context(session, self._organization_id)
            if self._revision is None:
                existing = session.scalar(
                    select(PipelineRuntimeStateModel).where(
                        PipelineRuntimeStateModel.store_id == self._store_id,
                        PipelineRuntimeStateModel.organization_id
                        == self._organization_id,
                    )
                )
                if existing is not None:
                    raise PipelineStateConflictError(
                        "pipeline state was concurrently created"
                    )
                session.add(
                    PipelineRuntimeStateModel(
                        store_id=self._store_id,
                        organization_id=self._organization_id,
                        snapshot=snapshot,
                        revision=0,
                        updated_at=now,
                    )
                )
                self._revision = 0
                return
            statement = (
                update(PipelineRuntimeStateModel)
                .where(
                    PipelineRuntimeStateModel.store_id == self._store_id,
                    PipelineRuntimeStateModel.organization_id == self._organization_id,
                    PipelineRuntimeStateModel.revision == self._revision,
                )
                .values(snapshot=snapshot, revision=self._revision + 1, updated_at=now)
            )
            if session.execute(statement).rowcount != 1:
                raise PipelineStateConflictError("pipeline state revision is stale")
            self._revision += 1

    def clear(self) -> None:
        with self._session_factory() as session, session.begin():
            apply_tenant_context(session, self._organization_id)
            session.execute(
                delete(PipelineRuntimeStateModel).where(
                    PipelineRuntimeStateModel.store_id == self._store_id,
                    PipelineRuntimeStateModel.organization_id == self._organization_id,
                )
            )
        self._revision = None
