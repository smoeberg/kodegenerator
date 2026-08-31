"""SQLAlchemy rows for tenant-scoped immutable Council configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class CouncilRoleConfigurationModel(Base):
    __tablename__ = "council_role_configurations"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    role_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    protocol_function: Mapped[str] = mapped_column(String(64), nullable=False)
    required_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    input_schema_ref: Mapped[str | None] = mapped_column(Text)
    output_schema_ref: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_ref: Mapped[str] = mapped_column(Text, nullable=False)
    independent_verification: Mapped[bool] = mapped_column(Boolean, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class CouncilTemplateModel(Base):
    __tablename__ = "council_templates"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class CouncilRoleAllocationModel(Base):
    __tablename__ = "council_role_allocations"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    role_id: Mapped[str] = mapped_column(String(128), nullable=False)
    role_version: Mapped[int] = mapped_column(Integer, nullable=False)
    independence_level: Mapped[str] = mapped_column(String(32), nullable=False)
    autonomy_level: Mapped[int] = mapped_column(Integer, nullable=False)
    hard_constraints: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "role_id", "role_version"],
            [
                "council_role_configurations.organization_id",
                "council_role_configurations.role_id",
                "council_role_configurations.version",
            ],
            name="fk_council_allocation_role_version",
        ),
    )


class CouncilRoleAllocationMemberModel(Base):
    __tablename__ = "council_role_allocation_members"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    allocation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    allocation_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    bot_profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    bot_profile_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    preference_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    fallback_rank: Mapped[int | None] = mapped_column(Integer)

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "allocation_id", "allocation_version"],
            [
                "council_role_allocations.organization_id",
                "council_role_allocations.allocation_id",
                "council_role_allocations.version",
            ],
            name="fk_council_member_allocation_version",
        ),
        ForeignKeyConstraint(
            ["organization_id", "bot_profile_id", "bot_profile_version"],
            [
                "bot_profiles.organization_id",
                "bot_profiles.bot_profile_id",
                "bot_profiles.version",
            ],
            name="fk_council_member_profile_version",
        ),
    )
