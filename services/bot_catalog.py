"""Application service for Bot Catalog integrity and AI-1 linkage."""

from __future__ import annotations

from infrastructure.persistence.bot_catalog_store import (
    BotCatalogNotFoundError,
    BotCatalogStore,
)
from phase4.agent_registry import AgentIdentity, AgentNotFoundError, AgentRegistry
from phase4.agent_registry.bot_profiles import (
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)


class BotCatalogValidationError(ValueError):
    """A catalog relationship or AI-1 capability binding is invalid."""


class BotCatalogService:
    def __init__(self, store: BotCatalogStore, registry: AgentRegistry) -> None:
        self.store = store
        self.registry = registry

    def create_connection(self, value: ProviderConnection) -> ProviderConnection:
        return self.store.add_connection(value)

    def disable_connection(
        self, organization_id: str, connection_id: str
    ) -> ProviderConnection:
        current = self.store.get_connection(organization_id, connection_id)
        if current is None:
            raise BotCatalogNotFoundError(connection_id)
        return self.store.add_connection(current.next_version(enabled=False))

    def create_deployment(self, value: ModelDeployment) -> ModelDeployment:
        connection = self.store.get_connection(
            value.organization_id, value.connection_id, value.connection_version
        )
        if connection is None:
            raise BotCatalogValidationError("connection version does not exist")
        if not connection.enabled:
            raise BotCatalogValidationError("connection version is disabled")
        return self.store.add_deployment(value)

    def create_profile(self, value: BotProfile) -> BotProfile:
        deployment = self.store.get_deployment(
            value.organization_id, value.deployment_id, value.deployment_revision
        )
        if deployment is None:
            raise BotCatalogValidationError("deployment revision does not exist")
        if deployment.status != "active":
            raise BotCatalogValidationError("deployment revision is not active")
        try:
            record = self.registry.get(AgentIdentity(value.agent_identity))
        except AgentNotFoundError as exc:
            raise BotCatalogValidationError("agent identity is not active") from exc
        declared = {capability.name for capability in record.capabilities}
        if not set(value.capabilities).issubset(declared):
            raise BotCatalogValidationError(
                "bot profile capabilities exceed the AI-1 declaration"
            )
        return self.store.add_profile(value)

    def disable_deployment(
        self, organization_id: str, deployment_id: str
    ) -> ModelDeployment:
        current = self.store.get_deployment(organization_id, deployment_id)
        if current is None:
            raise BotCatalogNotFoundError(deployment_id)
        return self.store.add_deployment(current.next_revision(status="disabled"))

    def disable_profile(self, organization_id: str, bot_profile_id: str) -> BotProfile:
        current = self.store.get_profile(organization_id, bot_profile_id)
        if current is None:
            raise BotCatalogNotFoundError(bot_profile_id)
        return self.store.add_profile(current.next_version(enabled=False))
