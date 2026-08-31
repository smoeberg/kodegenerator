"""SQLAlchemy rows for the tenant-scoped versioned Bot Catalog."""

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


class BotProviderConnectionModel(Base):
    __tablename__ = "bot_provider_connections"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    brand: Mapped[str] = mapped_column(String(255), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    secret_reference: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str | None] = mapped_column(String(128), nullable=True)
    data_boundary: Mapped[str] = mapped_column(String(32), nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class BotModelDeploymentModel(Base):
    __tablename__ = "bot_model_deployments"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    deployment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[str] = mapped_column(String(128), nullable=False)
    connection_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_family: Mapped[str] = mapped_column(String(255), nullable=False)
    max_context_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_output: Mapped[bool] = mapped_column(Boolean, nullable=False)
    tool_capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "connection_id", "connection_version"],
            [
                "bot_provider_connections.organization_id",
                "bot_provider_connections.connection_id",
                "bot_provider_connections.version",
            ],
            name="fk_bot_deployment_connection_version",
        ),
    )


class BotProfileModel(Base):
    __tablename__ = "bot_profiles"

    organization_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    bot_profile_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_identity: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    deployment_id: Mapped[str] = mapped_column(String(128), nullable=False)
    deployment_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    permitted_tools: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    data_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    budget_policy: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    concurrency_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "deployment_id", "deployment_revision"],
            [
                "bot_model_deployments.organization_id",
                "bot_model_deployments.deployment_id",
                "bot_model_deployments.revision",
            ],
            name="fk_bot_profile_deployment_revision",
        ),
    )
