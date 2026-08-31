import hashlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, update
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
    CouncilConfigurationStore,
)
from infrastructure.persistence.selection_models import (
    CouncilFrozenAssignmentModel,
    CouncilSelectionRunModel,
)
from infrastructure.persistence.selection_store import (
    CouncilSelectionConflictError,
    CouncilSelectionStore,
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
from phase4.verification.allocation_selector import (
    CouncilSelectionError,
    SelectionRequestContext,
)
from services.council_selection import CouncilSelectionService


def services(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'selection.db'}")
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
        CouncilSelectionRunModel.__table__,
        CouncilFrozenAssignmentModel.__table__,
    ):
        table.create(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    catalog = BotCatalogStore(factory)
    configuration = CouncilConfigurationStore(factory)
    selection_store = CouncilSelectionStore(factory)
    return (
        CouncilSelectionService(catalog, configuration, selection_store),
        catalog,
        configuration,
        selection_store,
        factory,
    )


def seed(catalog, configuration):
    connection = ProviderConnection(
        connection_id="connection-1",
        organization_id="org-1",
        brand="User chosen brand",
        adapter_type="openai-compatible",
        endpoint="https://provider.example/v1",
        secret_reference="secret://org-1/provider",
        region="eu-west",
        data_boundary="eu",
    )
    deployment = ModelDeployment(
        deployment_id="deployment-1",
        organization_id="org-1",
        connection_id="connection-1",
        connection_version=1,
        model_id="model-1",
        model_family="family-1",
        max_context_tokens=10_000,
        max_output_tokens=1_000,
    )
    profile = BotProfile(
        bot_profile_id="bot-1",
        organization_id="org-1",
        agent_identity=hashlib.sha256(b"agent").hexdigest(),
        display_name="Bot 1",
        deployment_id="deployment-1",
        deployment_revision=1,
        prompt_version="v1",
        capabilities=("architecture.review",),
        enabled=True,
    )
    catalog.add_connection(connection)
    catalog.add_deployment(deployment)
    catalog.add_profile(profile)
    role = CouncilRoleDefinition(
        role_id="reviewer",
        organization_id="org-1",
        name="Reviewer",
        purpose="Review a proposal",
        protocol_function=ProtocolFunction.REVIEWER,
        required_capabilities=("architecture.review",),
        output_schema_ref="review-v1",
        rubric_ref="review-rubric-v1",
    )
    configuration.add_role(role)
    configuration.add_template(
        CouncilTemplate(
            template_id="architecture",
            organization_id="org-1",
            name="Architecture",
            stages=(
                TemplateStage(
                    stage_id="review",
                    protocol_function=ProtocolFunction.REVIEWER,
                    role_versions=(("reviewer", 1),),
                ),
            ),
            approved_by="owner",
        )
    )
    configuration.add_allocation(
        RoleAllocationPool(
            allocation_id="reviewers",
            organization_id="org-1",
            role_id="reviewer",
            role_version=1,
            members=(AllocationMember("bot-1", 1, 1),),
            independence_level=IndependenceLevel.CONNECTION,
            autonomy_level=AutonomyLevel.HUMAN_APPROVES,
            approved_by="owner",
        )
    )


def context(template, marker="a"):
    return SelectionRequestContext(
        organization_id="org-1",
        scope_id="session-1",
        repository="smoeberg/kodegenerator",
        base_sha=marker * 40,
        requirements_fingerprint="1" * 64,
        architecture_fingerprint="2" * 64,
        contract_fingerprint="3" * 64,
        input_fingerprint="4" * 64,
        template_fingerprint=template.fingerprint,
    )


def test_selection_is_frozen_replayed_and_tenant_scoped(tmp_path) -> None:
    service, catalog, configuration, _, _ = services(tmp_path)
    seed(catalog, configuration)
    template = configuration.get_template("org-1", "architecture", 1)
    arguments = dict(
        organization_id="org-1",
        run_id="run-1",
        template_id="architecture",
        template_version=1,
        allocation_refs=(("reviewers", 1),),
        context=context(template),
    )
    selected = service.select_and_freeze(**arguments)
    replay = service.select_and_freeze(**arguments)
    assert replay == selected
    assert replay.assignments[0].bot_profile_id == "bot-1"
    assert service.get("org-2", "run-1") is None
    with pytest.raises(CouncilSelectionError, match="different input"):
        service.select_and_freeze(**{**arguments, "context": context(template, "b")})


def test_fingerprint_tampering_is_detected(tmp_path) -> None:
    service, catalog, configuration, store, factory = services(tmp_path)
    seed(catalog, configuration)
    template = configuration.get_template("org-1", "architecture", 1)
    service.select_and_freeze(
        organization_id="org-1",
        run_id="run-1",
        template_id="architecture",
        template_version=1,
        allocation_refs=(("reviewers", 1),),
        context=context(template),
    )
    with factory() as session, session.begin():
        session.execute(
            update(CouncilSelectionRunModel)
            .where(CouncilSelectionRunModel.run_id == "run-1")
            .values(rationale="tampered")
        )
    with pytest.raises(CouncilSelectionConflictError, match="fingerprint"):
        store.get("org-1", "run-1")


def test_blocked_decision_is_durable_and_replayed(tmp_path) -> None:
    service, catalog, configuration, _, factory = services(tmp_path)
    seed(catalog, configuration)
    template = configuration.get_template("org-1", "architecture", 1)
    with factory() as session, session.begin():
        profile = session.get(BotProfileModel, ("org-1", "bot-1", 1))
        profile.enabled = False
    arguments = dict(
        organization_id="org-1",
        run_id="blocked-run",
        template_id="architecture",
        template_version=1,
        allocation_refs=(("reviewers", 1),),
        context=context(template, "b"),
    )
    blocked = service.select_and_freeze(**arguments)
    assert blocked.status == "blocked"
    assert blocked.assignments == ()
    assert blocked.receipts[0].reason == "candidate_inactive"
    assert service.select_and_freeze(**arguments) == blocked


def test_two_workers_freeze_one_authoritative_decision(tmp_path) -> None:
    service, catalog, configuration, _, _ = services(tmp_path)
    seed(catalog, configuration)
    template = configuration.get_template("org-1", "architecture", 1)
    arguments = dict(
        organization_id="org-1",
        run_id="concurrent-run",
        template_id="architecture",
        template_version=1,
        allocation_refs=(("reviewers", 1),),
        context=context(template),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(
            executor.map(lambda _: service.select_and_freeze(**arguments), range(2))
        )
    assert results[0] == results[1]
    assert results[0].status == "selected"
