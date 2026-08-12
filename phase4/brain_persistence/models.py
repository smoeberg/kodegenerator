"""SQLAlchemy models for append-only epistemic records and materialized state."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models import Base


class KnowledgeRecordModel(Base):
    """Immutable epistemic record; never updated after insertion."""

    __tablename__ = "knowledge_records"

    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    subject: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_version: Mapped[int] = mapped_column(Integer, nullable=False)
    author_agent_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeStateModel(Base):
    """Materialized knowledge state protected by optimistic concurrency."""

    __tablename__ = "knowledge_states"

    subject: Mapped[str] = mapped_column(String(255), primary_key=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("subject", "version", name="uq_knowledge_state_subject_version"),
    )
