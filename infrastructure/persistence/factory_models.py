"""Durable rows for factory work packages and candidate evidence."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class FactoryWorkPackageModel(Base):
    __tablename__ = "factory_work_packages"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_package_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    logical_task_id: Mapped[str] = mapped_column(String(128), nullable=False)
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
            "organization_id", "idempotency_key", name="uq_factory_package_idempotency"
        ),
    )


class FactoryCandidateDeliveryModel(Base):
    __tablename__ = "factory_candidate_deliveries"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    work_package_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False)
    head_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "execution_id",
            "head_sha",
            name="uq_factory_candidate_execution_head",
        ),
    )


class FactoryCandidateSelectionModel(Base):
    __tablename__ = "factory_candidate_selections"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    selection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    logical_task_id: Mapped[str] = mapped_column(String(128), nullable=False)
    work_package_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    winner_candidate_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
