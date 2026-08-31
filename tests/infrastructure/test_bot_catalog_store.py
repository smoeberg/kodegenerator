from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.bot_catalog_models import (
    BotModelDeploymentModel,
    BotProfileModel,
    BotProviderConnectionModel,
)
from infrastructure.persistence.bot_catalog_store import BotCatalogStore
from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.agent_registry.bot_profiles import (
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)
from services.bot_catalog import BotCatalogService


def store(tmp_path) -> BotCatalogStore:
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    BotProviderConnectionModel.__table__.create(engine)
    BotModelDeploymentModel.__table__.create(engine)
    BotProfileModel.__table__.create(engine)
    return BotCatalogStore(sessionmaker(bind=engine, expire_on_commit=False))


def connection(org: str) -> ProviderConnection:
    return ProviderConnection(
        connection_id="shared",
        organization_id=org,
        brand="Mistral",
        adapter_type="mistral-api",
        endpoint="https://api.mistral.ai/v1",
        secret_reference=f"secret://{org}/mistral",
    )


def test_store_is_tenant_scoped_and_versions_are_immutable(tmp_path) -> None:
    catalog = store(tmp_path)
    catalog.add_connection(connection("org-1"))
    catalog.add_connection(connection("org-2"))
    disabled = catalog.add_connection(connection("org-1").next_version(enabled=False))

    assert catalog.get_connection("org-1", "shared", 1).enabled is True
    assert catalog.get_connection("org-1", "shared").version == disabled.version
    assert catalog.get_connection("org-2", "shared").organization_id == "org-2"
    assert catalog.get_connection("org-3", "shared") is None


def test_service_links_profile_to_exact_deployment_and_ai1_identity(tmp_path) -> None:
    catalog = store(tmp_path)
    registry = AgentRegistry()
    capability = Capability.create("architecture.design", AgentVersion(1, 0, 0))
    agent = registry.register(
        agent_type="architect",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.OTHER,
        capabilities=(capability,),
        instance_id="claude-01",
    )
    service = BotCatalogService(catalog, registry)
    service.create_connection(connection("org-1"))
    service.create_deployment(
        ModelDeployment(
            deployment_id="dep-1",
            organization_id="org-1",
            connection_id="shared",
            connection_version=1,
            model_id="model",
            model_family="family",
            max_context_tokens=10_000,
            max_output_tokens=1_000,
        )
    )
    value = service.create_profile(
        BotProfile(
            bot_profile_id="architect-1",
            organization_id="org-1",
            agent_identity=str(agent.identity),
            display_name="Claude Architect",
            deployment_id="dep-1",
            deployment_revision=1,
            prompt_version="v1",
            capabilities=("architecture.design",),
            enabled=True,
        )
    )
    assert catalog.get_profile("org-1", "architect-1") == value
    assert catalog.get_profile("org-2", "architect-1") is None
