"""Durable integration plans and terminal receipts."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class FactoryIntegrationPlanModel(Base):
    __tablename__ = "factory_integration_plans"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "workflow_id",
            "fingerprint",
            name="uq_factory_integration_plan",
        ),
        UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_factory_integration_idempotency",
        ),
    )


class FactoryIntegrationReceiptModel(Base):
    __tablename__ = "factory_integration_receipts"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    receipt_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    plan_id: Mapped[str] = mapped_column(String(128), nullable=False)
    plan_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "plan_fingerprint",
            name="uq_factory_successful_integration",
        ),
    )
