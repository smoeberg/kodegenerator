"""Tenant-scoped durable state for the Swarm control-plane adapter."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKeyConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class SwarmProjectDispatchModel(Base):
    """Dispatch registration attached to an existing canonical project."""

    __tablename__ = "swarm_project_dispatches"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"],
            ["projects.organization_id", "projects.id"],
            name="fk_swarm_dispatch_project",
            ondelete="CASCADE",
        ),
    )


class SwarmDispatchControlModel(Base):
    """One organization-wide dispatch switch shared by every API replica."""

    __tablename__ = "swarm_dispatch_controls"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
