"""Tenant-scoped immutable-version Bot Catalog persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.agent_registry.bot_profiles import (
    BotBudgetPolicy,
    BotDataPolicy,
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)

from .bot_catalog_models import (
    BotModelDeploymentModel,
    BotProfileModel,
    BotProviderConnectionModel,
)
from .database import apply_tenant_context


class BotCatalogConflictError(RuntimeError):
    """A version identity already exists or references invalid data."""


class BotCatalogNotFoundError(KeyError):
    """The tenant cannot see the requested catalog record."""


class BotCatalogStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def add_connection(self, value: ProviderConnection) -> ProviderConnection:
        self._insert(
            value.organization_id,
            BotProviderConnectionModel(
                organization_id=value.organization_id,
                connection_id=value.connection_id,
                version=value.version,
                brand=value.brand,
                adapter_type=value.adapter_type,
                endpoint=value.endpoint,
                secret_reference=value.secret_reference,
                region=value.region,
                data_boundary=value.data_boundary,
                concurrency_limit=value.concurrency_limit,
                enabled=value.enabled,
                created_at=value.created_at,
                updated_at=value.updated_at,
            ),
        )
        return value

    def get_connection(
        self, organization_id: str, connection_id: str, version: int | None = None
    ) -> ProviderConnection | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            query = select(BotProviderConnectionModel).where(
                BotProviderConnectionModel.organization_id == organization_id,
                BotProviderConnectionModel.connection_id == connection_id,
            )
            query = (
                query.where(BotProviderConnectionModel.version == version)
                if version is not None
                else query.order_by(BotProviderConnectionModel.version.desc()).limit(1)
            )
            row = session.scalar(query)
            return None if row is None else self._connection(row)

    def list_connections(
        self, organization_id: str, *, include_disabled: bool = True
    ) -> tuple[ProviderConnection, ...]:
        values = tuple(
            self._connection(row)
            for row in self._latest_rows(
                organization_id,
                BotProviderConnectionModel,
                BotProviderConnectionModel.connection_id,
                BotProviderConnectionModel.version,
            )
        )
        return (
            values
            if include_disabled
            else tuple(value for value in values if value.enabled)
        )

    def add_deployment(self, value: ModelDeployment) -> ModelDeployment:
        self._insert(
            value.organization_id,
            BotModelDeploymentModel(
                organization_id=value.organization_id,
                deployment_id=value.deployment_id,
                revision=value.revision,
                connection_id=value.connection_id,
                connection_version=value.connection_version,
                model_id=value.model_id,
                model_family=value.model_family,
                max_context_tokens=value.max_context_tokens,
                max_output_tokens=value.max_output_tokens,
                structured_output=value.structured_output,
                tool_capabilities=list(value.tool_capabilities),
                status=value.status,
                created_at=value.created_at,
                updated_at=value.updated_at,
            ),
        )
        return value

    def get_deployment(
        self, organization_id: str, deployment_id: str, revision: int | None = None
    ) -> ModelDeployment | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            query = select(BotModelDeploymentModel).where(
                BotModelDeploymentModel.organization_id == organization_id,
                BotModelDeploymentModel.deployment_id == deployment_id,
            )
            query = (
                query.where(BotModelDeploymentModel.revision == revision)
                if revision is not None
                else query.order_by(BotModelDeploymentModel.revision.desc()).limit(1)
            )
            row = session.scalar(query)
            return None if row is None else self._deployment(row)

    def list_deployments(self, organization_id: str) -> tuple[ModelDeployment, ...]:
        return tuple(
            self._deployment(row)
            for row in self._latest_rows(
                organization_id,
                BotModelDeploymentModel,
                BotModelDeploymentModel.deployment_id,
                BotModelDeploymentModel.revision,
            )
        )

    def add_profile(self, value: BotProfile) -> BotProfile:
        self._insert(
            value.organization_id,
            BotProfileModel(
                organization_id=value.organization_id,
                bot_profile_id=value.bot_profile_id,
                version=value.version,
                agent_identity=value.agent_identity,
                display_name=value.display_name,
                deployment_id=value.deployment_id,
                deployment_revision=value.deployment_revision,
                prompt_version=value.prompt_version,
                capabilities=list(value.capabilities),
                permitted_tools=list(value.permitted_tools),
                data_policy=value.data_policy.canonical(),
                budget_policy=value.budget_policy.canonical(),
                concurrency_limit=value.concurrency_limit,
                enabled=value.enabled,
                fingerprint=value.fingerprint,
                created_at=value.created_at,
                updated_at=value.updated_at,
            ),
        )
        return value

    def get_profile(
        self, organization_id: str, bot_profile_id: str, version: int | None = None
    ) -> BotProfile | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            query = select(BotProfileModel).where(
                BotProfileModel.organization_id == organization_id,
                BotProfileModel.bot_profile_id == bot_profile_id,
            )
            query = (
                query.where(BotProfileModel.version == version)
                if version is not None
                else query.order_by(BotProfileModel.version.desc()).limit(1)
            )
            row = session.scalar(query)
            return None if row is None else self._profile(row)

    def list_profiles(
        self, organization_id: str, *, include_disabled: bool = True
    ) -> tuple[BotProfile, ...]:
        values = tuple(
            self._profile(row)
            for row in self._latest_rows(
                organization_id,
                BotProfileModel,
                BotProfileModel.bot_profile_id,
                BotProfileModel.version,
            )
        )
        return (
            values
            if include_disabled
            else tuple(value for value in values if value.enabled)
        )

    def _insert(self, organization_id: str, row: object) -> None:
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, organization_id)
                session.add(row)
        except IntegrityError as exc:
            raise BotCatalogConflictError(
                "bot catalog version already exists or references invalid data"
            ) from exc

    def _latest_rows(self, organization_id, model, identity_column, version_column):
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            rows = session.scalars(
                select(model)
                .where(model.organization_id == organization_id)
                .order_by(identity_column, version_column.desc())
            ).all()
            latest: dict[str, Any] = {}
            for row in rows:
                latest.setdefault(str(getattr(row, identity_column.key)), row)
            return tuple(latest[key] for key in sorted(latest))

    @staticmethod
    def _connection(row: BotProviderConnectionModel) -> ProviderConnection:
        return ProviderConnection(
            connection_id=row.connection_id,
            organization_id=row.organization_id,
            brand=row.brand,
            adapter_type=row.adapter_type,
            endpoint=row.endpoint,
            secret_reference=row.secret_reference,
            region=row.region,
            data_boundary=row.data_boundary,
            concurrency_limit=row.concurrency_limit,
            enabled=row.enabled,
            version=row.version,
            created_at=_aware_utc(row.created_at),
            updated_at=_aware_utc(row.updated_at),
        )

    @staticmethod
    def _deployment(row: BotModelDeploymentModel) -> ModelDeployment:
        return ModelDeployment(
            deployment_id=row.deployment_id,
            organization_id=row.organization_id,
            connection_id=row.connection_id,
            connection_version=row.connection_version,
            model_id=row.model_id,
            model_family=row.model_family,
            max_context_tokens=row.max_context_tokens,
            max_output_tokens=row.max_output_tokens,
            structured_output=row.structured_output,
            tool_capabilities=tuple(row.tool_capabilities),
            status=row.status,
            revision=row.revision,
            created_at=_aware_utc(row.created_at),
            updated_at=_aware_utc(row.updated_at),
        )

    @staticmethod
    def _profile(row: BotProfileModel) -> BotProfile:
        data_policy = row.data_policy
        budget_policy = row.budget_policy
        return BotProfile(
            bot_profile_id=row.bot_profile_id,
            organization_id=row.organization_id,
            agent_identity=row.agent_identity,
            display_name=row.display_name,
            deployment_id=row.deployment_id,
            deployment_revision=row.deployment_revision,
            prompt_version=row.prompt_version,
            capabilities=tuple(row.capabilities),
            permitted_tools=tuple(row.permitted_tools),
            data_policy=BotDataPolicy(
                boundary=data_policy["boundary"],
                allowed_regions=tuple(data_policy.get("allowed_regions") or ()),
                source_code_allowed=bool(data_policy["source_code_allowed"]),
            ),
            budget_policy=BotBudgetPolicy(
                max_cost_minor_units=budget_policy.get("max_cost_minor_units"),
                max_input_tokens=int(budget_policy["max_input_tokens"]),
                max_output_tokens=int(budget_policy["max_output_tokens"]),
            ),
            concurrency_limit=row.concurrency_limit,
            enabled=row.enabled,
            version=row.version,
            created_at=_aware_utc(row.created_at),
            updated_at=_aware_utc(row.updated_at),
        )


def _aware_utc(value: datetime) -> datetime:
    """Restore UTC lost by SQLite's timezone-naive datetime adapter."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
