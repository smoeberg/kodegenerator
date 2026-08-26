"""SQLAlchemy models for the durable organization-scoped Council runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.persistence.models import Base


class CouncilSessionModel(Base):
    __tablename__ = "council_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    hypothesis_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hypothesis_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    context_packet_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    current_round: Mapped[int] = mapped_column(Integer, nullable=False)
    max_rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hypothesis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    history: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "session_id", name="uq_council_session_org_id"
        ),
    )


class CouncilDisputeModel(Base):
    __tablename__ = "council_disputes"

    dispute_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hypothesis_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_dispute_org_session",
            ondelete="CASCADE",
        ),
    )


class CouncilVoteModel(Base):
    __tablename__ = "council_votes"

    vote_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(String(128), nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_vote_org_session",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "session_id",
            "round_number",
            "agent_id",
            name="uq_council_vote_org_session_round_agent",
        ),
    )


class CouncilEvidenceBindingModel(Base):
    __tablename__ = "council_evidence_bindings"

    binding_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hypothesis_id: Mapped[str] = mapped_column(String(128), nullable=False)
    hypothesis_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    context_packet_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    content_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_evidence_org_session",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id",
            "session_id",
            "evidence_id",
            name="uq_council_evidence_org_session_id",
        ),
    )


class CouncilFailureObservationModel(Base):
    __tablename__ = "council_failure_observations"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    hypothesis_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    execution_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    fingerprint_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    failure: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "session_id"],
            ["council_sessions.organization_id", "council_sessions.session_id"],
            name="fk_council_failure_org_session",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "organization_id", "event_id", name="uq_council_failure_org_event"
        ),
        UniqueConstraint(
            "organization_id",
            "execution_id",
            name="uq_council_failure_org_execution",
        ),
    )


class CouncilOutboxEventModel(Base):
    __tablename__ = "council_outbox_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    aggregate_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
