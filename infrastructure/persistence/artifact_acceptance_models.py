"""SQLAlchemy model for immutable multi-spec artifact acceptances."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .models import Base


class ArtifactAcceptanceModel(Base):
    """Append-only tenant-scoped human acceptance record."""

    __tablename__ = "artifact_acceptances"

    acceptance_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    repository: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    artifact_set_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bundle_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_by: Mapped[str] = mapped_column(String(128), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rationale: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    manifest_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    specs_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    acceptance_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "command_id",
            name="uq_artifact_acceptance_command",
        ),
        UniqueConstraint(
            "organization_id",
            "bundle_fingerprint",
            "contract_fingerprint",
            name="uq_artifact_acceptance_bundle_contract",
        ),
    )


__all__ = ["ArtifactAcceptanceModel"]
