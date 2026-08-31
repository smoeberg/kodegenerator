"""Durable rows for frozen bot selections and decision receipts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class CouncilSelectionRunModel(Base):
    __tablename__ = "bot_selection_decisions"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_id: Mapped[str] = mapped_column(String(128), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    template_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    repository: Mapped[str] = mapped_column(Text, nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    selector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    receipts: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "run_id", name="uq_bot_selection_run"
        ),
        ForeignKeyConstraint(
            ["organization_id", "template_id", "template_version"],
            [
                "council_templates.organization_id",
                "council_templates.template_id",
                "council_templates.version",
            ],
            name="fk_council_selection_template_version",
        ),
    )


class CouncilFrozenAssignmentModel(Base):
    __tablename__ = "bot_session_assignments"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assignment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role_version: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    allocation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    bot_profile_id: Mapped[str] = mapped_column(String(128), nullable=False)
    bot_profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_identity: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    deployment_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    deployment_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    connection_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(128), nullable=False)
    repository: Mapped[str] = mapped_column(Text, nullable=False)
    base_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "decision_id",
            "assignment_index",
            name="uq_council_assignment_order",
        ),
        ForeignKeyConstraint(
            ["organization_id", "decision_id"],
            [
                "bot_selection_decisions.organization_id",
                "bot_selection_decisions.decision_id",
            ],
            name="fk_council_assignment_run",
        ),
        ForeignKeyConstraint(
            ["organization_id", "role_id", "role_version"],
            [
                "council_role_configurations.organization_id",
                "council_role_configurations.role_id",
                "council_role_configurations.version",
            ],
            name="fk_council_assignment_role",
        ),
        ForeignKeyConstraint(
            ["organization_id", "allocation_id", "allocation_version"],
            [
                "council_role_allocations.organization_id",
                "council_role_allocations.allocation_id",
                "council_role_allocations.version",
            ],
            name="fk_council_assignment_allocation",
        ),
        ForeignKeyConstraint(
            ["organization_id", "bot_profile_id", "bot_profile_version"],
            [
                "bot_profiles.organization_id",
                "bot_profiles.bot_profile_id",
                "bot_profiles.version",
            ],
            name="fk_council_assignment_profile",
        ),
    )
