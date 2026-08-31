import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.bot_catalog_models import (
    BotModelDeploymentModel,
    BotProfileModel,
    BotProviderConnectionModel,
)
from infrastructure.persistence.bot_catalog_store import BotCatalogStore
from infrastructure.persistence.council_configuration_models import (
    CouncilRoleAllocationMemberModel,
    CouncilRoleAllocationModel,
    CouncilRoleConfigurationModel,
    CouncilTemplateModel,
)
from infrastructure.persistence.council_configuration_store import (
    CouncilConfigurationError,
    CouncilConfigurationStore,
)
from phase4.agent_registry.bot_profiles import (
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)
from phase4.council.configuration import (
    AllocationMember,
    AutonomyLevel,
    CouncilRoleDefinition,
    CouncilTemplate,
    IndependenceLevel,
    ProtocolFunction,
    RoleAllocationPool,
    TemplateStage,
)


def stores(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'council.db'}")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    for table in (
        BotProviderConnectionModel.__table__,
        BotModelDeploymentModel.__table__,
        BotProfileModel.__table__,
        CouncilRoleConfigurationModel.__table__,
        CouncilTemplateModel.__table__,
        CouncilRoleAllocationModel.__table__,
        CouncilRoleAllocationMemberModel.__table__,
    ):
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return BotCatalogStore(factory), CouncilConfigurationStore(factory)


def seed_profile(
    catalog: BotCatalogStore, org: str, profile_id: str, capabilities: tuple[str, ...]
) -> None:
    catalog.add_connection(
        ProviderConnection(
            connection_id=f"connection-{profile_id}",
            organization_id=org,
            brand="Any AI",
            adapter_type="openai-compatible",
            endpoint="http://internal-ai/v1",
            secret_reference=f"secret://{org}/{profile_id}",
        )
    )
    catalog.add_deployment(
        ModelDeployment(
            deployment_id=f"deployment-{profile_id}",
            organization_id=org,
            connection_id=f"connection-{profile_id}",
            connection_version=1,
            model_id="model",
            model_family="family",
            max_context_tokens=10_000,
            max_output_tokens=1_000,
        )
    )
    catalog.add_profile(
        BotProfile(
            bot_profile_id=profile_id,
            organization_id=org,
            agent_identity="a" * 64,
            display_name=profile_id,
            deployment_id=f"deployment-{profile_id}",
            deployment_revision=1,
            prompt_version="v1",
            capabilities=capabilities,
            enabled=True,
        )
    )


def test_roles_templates_and_allocations_round_trip_and_isolate_tenants(
    tmp_path,
) -> None:
    catalog, store = stores(tmp_path)
    seed_profile(catalog, "org-1", "architect-1", ("architecture.design",))
    value = CouncilRoleDefinition(
        role_id="architect",
        organization_id="org-1",
        name="Architect",
        purpose="Propose architecture",
        protocol_function=ProtocolFunction.PROPOSER,
        required_capabilities=("architecture.design",),
        output_schema_ref="architecture-v1",
        rubric_ref="architecture-rubric-v1",
    )
    store.add_role(value)
    template = CouncilTemplate(
        template_id="architecture",
        organization_id="org-1",
        name="Architecture",
        stages=(
            TemplateStage(
                stage_id="proposal",
                protocol_function=ProtocolFunction.PROPOSER,
                role_versions=(("architect", 1),),
            ),
        ),
        approved_by="owner",
    )
    store.add_template(template)
    pool = RoleAllocationPool(
        allocation_id="architects",
        organization_id="org-1",
        role_id="architect",
        role_version=1,
        members=(AllocationMember("architect-1", 1, 1),),
        independence_level=IndependenceLevel.CONNECTION,
        autonomy_level=AutonomyLevel.HUMAN_APPROVES,
        approved_by="owner",
    )
    store.add_allocation(pool)
    assert store.get_role("org-1", "architect") == value
    assert store.get_template("org-1", "architecture") == template
    assert store.get_allocation("org-1", "architects") == pool
    assert store.get_role("org-2", "architect") is None


def test_allocation_rejects_profile_without_role_capability(tmp_path) -> None:
    catalog, store = stores(tmp_path)
    seed_profile(catalog, "org-1", "writer-1", ("code.write",))
    store.add_role(
        CouncilRoleDefinition(
            role_id="architect",
            organization_id="org-1",
            name="Architect",
            purpose="Propose architecture",
            protocol_function=ProtocolFunction.PROPOSER,
            required_capabilities=("architecture.design",),
            output_schema_ref="architecture-v1",
            rubric_ref="rubric-v1",
        )
    )
    with pytest.raises(CouncilConfigurationError, match="lacks"):
        store.add_allocation(
            RoleAllocationPool(
                allocation_id="invalid",
                organization_id="org-1",
                role_id="architect",
                role_version=1,
                members=(AllocationMember("writer-1", 1, 1),),
                independence_level=IndependenceLevel.CONNECTION,
                autonomy_level=AutonomyLevel.HUMAN_APPROVES,
                approved_by="owner",
            )
        )
