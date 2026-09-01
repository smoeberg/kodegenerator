"""Tenant-scoped worker service identities."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class WorkerServiceIdentityModel(Base):
    __tablename__ = "worker_service_identities"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    service_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    credential_hash: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    credential_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
