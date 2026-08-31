"""SQLAlchemy rows for the append-only evaluation and learning ledger."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class EvaluationRubricModel(Base):
    __tablename__ = "evaluation_rubrics"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    rubric_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_classes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    criteria: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    pass_threshold: Mapped[float] = mapped_column(Float, nullable=False)
    independence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class EvaluationRecordModel(Base):
    __tablename__ = "evaluation_records"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_class: Mapped[str] = mapped_column(String(128), nullable=False)
    subject_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    rubric_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    rubric_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    producer: Mapped[dict] = mapped_column(JSON, nullable=False)
    evaluator: Mapped[dict | None] = mapped_column(JSON)
    checks: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    semantic_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    hard_failures: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    provenance: Mapped[list[list]] = mapped_column(JSON, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class BotPerformanceObservationModel(Base):
    __tablename__ = "bot_performance_observations"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_context: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    rubric_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source: Mapped[str] = mapped_column(String(128), nullable=False)
    ledger_position: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_observation_id: Mapped[str | None] = mapped_column(String(64))
    event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "ledger_position", name="uq_performance_ledger_position"
        ),
    )


class BotPerformanceSnapshotModel(Base):
    __tablename__ = "bot_performance_snapshots"
    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    bot_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role_id: Mapped[str] = mapped_column(String(128), nullable=False)
    task_context: Mapped[str] = mapped_column(Text, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    definitions: Mapped[list[list]] = mapped_column(JSON, nullable=False)
    values: Mapped[list[list]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    decay_version: Mapped[str] = mapped_column(String(64), nullable=False)
    exclusions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    ledger_position: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
