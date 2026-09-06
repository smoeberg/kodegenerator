"""SQLAlchemy persistence model for authoritative delivery certificates."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .models import Base


class DeliveryCertificateModel(Base):
    """Append-only tenant-scoped certification result."""

    __tablename__ = "delivery_certificates"

    certificate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    candidate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    contract_id: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(32), nullable=False)
    contract_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    certified_by: Mapped[str] = mapped_column(String(128), nullable=False)
    certified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    certificate_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "candidate_id",
            "contract_fingerprint",
            name="uq_delivery_certificate_candidate_contract",
        ),
        UniqueConstraint(
            "organization_id",
            "command_id",
            name="uq_delivery_certificate_command",
        ),
    )


__all__ = ["DeliveryCertificateModel"]
