"""Durable persistence models for Work Queue v0 (WQ-102)."""

from __future__ import annotations

from datetime import datetime
from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class WorkUnitModel(Base):
    """Organization-scoped durable work unit row (current projection)."""

    __tablename__ = "work_units"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    state: Mapped[str] = mapped_column(String(64), nullable=False)
    required_capability: Mapped[dict] = mapped_column(JSON, nullable=False)
    depends_on: Mapped[list] = mapped_column(JSON, nullable=False)
    depends_on_snapshot: Mapped[list] = mapped_column(JSON, nullable=False)
    base_version: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    allowed_resources: Mapped[list] = mapped_column(JSON, nullable=False)
    acceptance_refs: Mapped[list] = mapped_column(JSON, nullable=False)
    delivered_artifact_version: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    previous_worker: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rework_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WorkUnitRevisionModel(Base):
    """Append-only tenant-scoped immutable WorkUnit revision history."""

    __tablename__ = "work_unit_revisions"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_unit_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["WorkUnitModel", "WorkUnitRevisionModel"]
