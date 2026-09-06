"""SQLAlchemy persistence model for immutable requirement traceability manifests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .models import Base


class RequirementTraceabilityModel(Base):
    """Append-only tenant-scoped requirement-to-artifact traceability artifact."""

    __tablename__ = "requirement_traceability_manifests"

    manifest_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    certificate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    plan_request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requirements_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    links_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    manifest_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "command_id",
            name="uq_requirement_traceability_command",
        ),
    )


__all__ = ["RequirementTraceabilityModel"]
