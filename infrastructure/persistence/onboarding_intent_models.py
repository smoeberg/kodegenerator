"""Tenant-scoped durable persistence model for onboarding intents."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKeyConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .models import Base


class OnboardingIntentModel(Base):
    """Immutable persisted onboarding declaration and supersession edge."""

    __tablename__ = "onboarding_intents"

    intent_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_repository: Mapped[str] = mapped_column(String(1024), nullable=False, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    target_stack: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    supersedes_intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    declared_by: Mapped[str] = mapped_column(String(128), nullable=False)
    declared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "intent_id",
            name="uq_onboarding_intent_org_id",
        ),
        UniqueConstraint(
            "organization_id",
            "supersedes_intent_id",
            name="uq_onboarding_intent_single_successor",
        ),
        ForeignKeyConstraint(
            ["organization_id", "declared_by"],
            ["actors.organization_id", "actors.id"],
            name="fk_onboarding_intent_actor_org",
        ),
        ForeignKeyConstraint(
            ["organization_id", "supersedes_intent_id"],
            ["onboarding_intents.organization_id", "onboarding_intents.intent_id"],
            name="fk_onboarding_intent_supersedes_org",
        ),
    )
