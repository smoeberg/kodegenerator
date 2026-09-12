"""Application service for Bot Catalog integrity and AI-1 linkage."""

from __future__ import annotations

from threading import RLock

from infrastructure.persistence.bot_catalog_store import (
    BotCatalogConflictError,
    BotCatalogNotFoundError,
    BotCatalogStore,
)
from phase4.agent_registry import (
    AgentIdentity,
    AgentNotFoundError,
    AgentRecord,
    AgentRegistry,
    AgentRole,
    AgentVersion,
    Capability,
    DuplicateIdentityError,
)
from phase4.agent_registry.bot_profiles import (
    BotBudgetPolicy,
    BotDataPolicy,
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
        self._profile_lock = RLock()

    @staticmethod
    def _agent_declaration(
        organization_id: str, bot_profile_id: str, capabilities: tuple[str, ...]
    ) -> tuple[
        str, AgentVersion, AgentRole, tuple[Capability, ...], str, str, AgentIdentity
    ]:
        version = AgentVersion(1, 0, 0)
        role = AgentRole.OTHER
        capability_values = tuple(
            Capability.create(
                name,
                version,
                {"bot_profile_id": bot_profile_id, "organization_id": organization_id},
            )
            for name in tuple(sorted(set(capabilities)))
        )
        instance_id = f"{organization_id}:{bot_profile_id}"
        trust_anchor = f"organization:{organization_id}:bot-profile:{bot_profile_id}"
        identity = AgentIdentity.derive(
            agent_type="bot-profile",
            version=version,
            role=role,
            capabilities=capability_values,
            trust_anchor=trust_anchor,
            instance_id=instance_id,
        )
        return (
            "bot-profile",
            version,
            role,
            capability_values,
            instance_id,
            trust_anchor,
            identity,
        )

    def _ensure_agent(
        self, organization_id: str, bot_profile_id: str, capabilities: tuple[str, ...]
    ) -> tuple[AgentRecord, bool]:
        (
            agent_type,
            version,
            role,
            capability_values,
            instance_id,
            trust_anchor,
            identity,
        ) = self._agent_declaration(organization_id, bot_profile_id, capabilities)
        try:
            record = self.registry.register(
                agent_type=agent_type,
                version=version,
                role=role,
                capabilities=capability_values,
                trust_anchor=trust_anchor,
                instance_id=instance_id,
                actor="bot-catalog-service",
            )
            return record, True
        except DuplicateIdentityError:
            try:
                record = self.registry.get(identity, include_inactive=True)
            except AgentNotFoundError as exc:
                raise BotCatalogValidationError("agent identity conflict") from exc
            expected = (
                agent_type,
                instance_id,
                version,
                role,
                capability_values,
                trust_anchor,
            )
            actual = (
                record.agent_type,
                record.instance_id,
                record.version,
                record.role,
                record.capabilities,
                record.trust_anchor,
            )
            if actual != expected:
                raise BotCatalogValidationError("agent identity conflict")
            if not record.active:
                raise BotCatalogValidationError("agent identity is inactive")
            return record, False

    def rehydrate_registry(self) -> None:
        """Rebuild active AI-1 declarations from persisted profile truth."""
        with self._profile_lock, self.registry.registration_transaction():
            for profile in self.store.list_profiles_for_registry_rehydration():
                *_, identity = self._agent_declaration(
                    profile.organization_id,
                    profile.bot_profile_id,
                    profile.capabilities,
                )
                if profile.agent_identity != str(identity):
                    raise BotCatalogValidationError(
                        "persisted bot profile has inconsistent agent identity"
                    )
                self._ensure_agent(
                    profile.organization_id,
                    profile.bot_profile_id,
                    profile.capabilities,
                )

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

    def create_profile(
        self,
        *,
        bot_profile_id: str,
        organization_id: str,
        display_name: str,
        deployment_id: str,
        deployment_revision: int,
        prompt_version: str,
        capabilities: tuple[str, ...],
        permitted_tools: tuple[str, ...] = (),
        data_policy: BotDataPolicy | None = None,
        budget_policy: BotBudgetPolicy | None = None,
        concurrency_limit: int = 1,
        enabled: bool = False,
    ) -> BotProfile:
        # Construct all caller-controlled values before touching the registry.
        capabilities = tuple(sorted(set(capabilities)))
        permitted_tools = tuple(sorted(set(permitted_tools)))
        *_, identity = self._agent_declaration(
            organization_id, bot_profile_id, capabilities
        )
        value = BotProfile(
            bot_profile_id=bot_profile_id,
            organization_id=organization_id,
            agent_identity=str(identity),
            display_name=display_name,
            deployment_id=deployment_id,
            deployment_revision=deployment_revision,
            prompt_version=prompt_version,
            capabilities=capabilities,
            permitted_tools=permitted_tools,
            data_policy=data_policy or BotDataPolicy(),
            budget_policy=budget_policy or BotBudgetPolicy(),
            concurrency_limit=concurrency_limit,
            enabled=enabled,
        )
        deployment = self.store.get_deployment(
            value.organization_id, value.deployment_id, value.deployment_revision
        )
        if deployment is None:
            raise BotCatalogValidationError("deployment revision does not exist")
        if deployment.status != "active":
            raise BotCatalogValidationError("deployment revision is not active")
        with self._profile_lock, self.registry.registration_transaction():
            record, created = self._ensure_agent(
                organization_id, bot_profile_id, capabilities
            )
            try:
                current = self.store.get_profile(organization_id, bot_profile_id)
                if current is not None:
                    comparable = (
                        "agent_identity",
                        "display_name",
                        "deployment_id",
                        "deployment_revision",
                        "prompt_version",
                        "capabilities",
                        "permitted_tools",
                        "data_policy",
                        "budget_policy",
                        "concurrency_limit",
                        "enabled",
                    )
                    if all(
                        getattr(current, field) == getattr(value, field)
                        for field in comparable
                    ):
                        return current
                    raise BotCatalogConflictError(
                        "bot profile already exists with different values"
                    )
                return self.store.add_profile(value)
            except Exception:
                if created:
                    self.registry.rollback_registration(
                        record.identity, actor="bot-catalog-service"
                    )
                raise

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
