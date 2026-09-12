from threading import Event, Thread

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.bot_catalog_models import (
    BotModelDeploymentModel,
    BotProfileModel,
    BotProviderConnectionModel,
)
from infrastructure.persistence.bot_catalog_store import (
    BotCatalogConflictError,
    BotCatalogStore,
)
from phase4.agent_registry import AgentIdentity, AgentRegistry
from phase4.agent_registry.bot_profiles import (
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)
from services.bot_catalog import BotCatalogService, BotCatalogValidationError


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


def test_service_derives_and_links_profile_to_tenant_bound_ai1_identity(
    tmp_path,
) -> None:
    catalog = store(tmp_path)
    registry = AgentRegistry()
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
        bot_profile_id="architect-1",
        organization_id="org-1",
        display_name="Claude Architect",
        deployment_id="dep-1",
        deployment_revision=1,
        prompt_version="v1",
        capabilities=("architecture.design",),
        enabled=True,
    )
    registered = registry.get(AgentIdentity(value.agent_identity))
    assert registered.instance_id == "org-1:architect-1"
    assert registered.agent_type == "bot-profile"
    assert registered.trust_anchor == "organization:org-1:bot-profile:architect-1"
    assert catalog.get_profile("org-1", "architect-1") == value
    assert catalog.get_profile("org-2", "architect-1") is None


def test_profile_retry_is_idempotent_and_different_retry_conflicts(tmp_path) -> None:
    catalog = store(tmp_path)
    registry = AgentRegistry()
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
    values = {
        "bot_profile_id": "architect-1",
        "organization_id": "org-1",
        "display_name": "Architect",
        "deployment_id": "dep-1",
        "deployment_revision": 1,
        "prompt_version": "v1",
        "capabilities": ("architecture.design",),
    }
    first = service.create_profile(**values)
    assert service.create_profile(**values) == first
    assert len(registry.list()) == 1
    with pytest.raises(BotCatalogConflictError):
        service.create_profile(**(values | {"display_name": "Different"}))
    assert len(registry.list()) == 1


def test_profile_creation_fails_closed_for_inactive_derived_identity(tmp_path) -> None:
    catalog = store(tmp_path)
    registry = AgentRegistry()
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
    values = {
        "bot_profile_id": "architect-1",
        "organization_id": "org-1",
        "display_name": "Architect",
        "deployment_id": "dep-1",
        "deployment_revision": 1,
        "prompt_version": "v1",
        "capabilities": ("architecture.design",),
    }
    created = service.create_profile(**values)
    registry.deactivate(AgentIdentity(created.agent_identity), actor="test")
    with pytest.raises(BotCatalogValidationError, match="inactive"):
        service.create_profile(**values)


def test_new_registration_is_compensated_when_profile_persistence_fails(
    tmp_path, monkeypatch
) -> None:
    catalog = store(tmp_path)
    registry = AgentRegistry()
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
    monkeypatch.setattr(
        catalog, "add_profile", lambda _: (_ for _ in ()).throw(RuntimeError("db"))
    )
    with pytest.raises(RuntimeError, match="db"):
        service.create_profile(
            bot_profile_id="architect-1",
            organization_id="org-1",
            display_name="Architect",
            deployment_id="dep-1",
            deployment_revision=1,
            prompt_version="v1",
            capabilities=("architecture.design",),
        )
    assert registry.list() == []
    assert registry.audit_trail()[-1]["operation"] == "registration_rolled_back"


def test_registry_rehydrates_existing_profile_after_process_restart(tmp_path) -> None:
    catalog = store(tmp_path)
    first_registry = AgentRegistry()
    first = BotCatalogService(catalog, first_registry)
    first.create_connection(connection("org-1"))
    first.create_deployment(
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
    profile = first.create_profile(
        bot_profile_id="architect-1",
        organization_id="org-1",
        display_name="Architect",
        deployment_id="dep-1",
        deployment_revision=1,
        prompt_version="v1",
        capabilities=("architecture.design",),
    )

    restarted_registry = AgentRegistry()
    restarted = BotCatalogService(catalog, restarted_registry)
    restarted.rehydrate_registry()

    assert restarted_registry.get(AgentIdentity(profile.agent_identity)).active is True


def test_production_composition_rehydrates_after_dependency_cache_reset(
    tmp_path, monkeypatch
) -> None:
    from api.dependencies import get_agent_registry, get_bot_catalog_service

    database_url = f"sqlite:///{tmp_path / 'composition.db'}"
    engine = create_engine(database_url)
    BotProviderConnectionModel.__table__.create(engine)
    BotModelDeploymentModel.__table__.create(engine)
    BotProfileModel.__table__.create(engine)
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_bot_catalog_service.cache_clear()
    get_agent_registry.cache_clear()
    first = get_bot_catalog_service()
    first.create_connection(connection("org-1"))
    first.create_deployment(
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
    profile = first.create_profile(
        bot_profile_id="architect-1",
        organization_id="org-1",
        display_name="Architect",
        deployment_id="dep-1",
        deployment_revision=1,
        prompt_version="v1",
        capabilities=("architecture.design",),
    )

    get_bot_catalog_service.cache_clear()
    get_agent_registry.cache_clear()
    restarted = get_bot_catalog_service()

    assert restarted.registry.get(AgentIdentity(profile.agent_identity)).active is True
    get_bot_catalog_service.cache_clear()
    get_agent_registry.cache_clear()


def test_registry_rehydration_fails_closed_on_inconsistent_persisted_identity(
    tmp_path,
) -> None:
    catalog = store(tmp_path)
    catalog.add_connection(connection("org-1"))
    catalog.add_deployment(
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
    catalog.add_profile(
        BotProfile(
            bot_profile_id="architect-1",
            organization_id="org-1",
            agent_identity="1" * 64,
            display_name="Architect",
            deployment_id="dep-1",
            deployment_revision=1,
            prompt_version="v1",
            capabilities=("architecture.design",),
        )
    )

    with pytest.raises(BotCatalogValidationError, match="inconsistent"):
        BotCatalogService(catalog, AgentRegistry()).rehydrate_registry()


def test_failed_create_cannot_remove_registration_reused_by_concurrent_success(
    tmp_path, monkeypatch
) -> None:
    catalog = store(tmp_path)
    registry = AgentRegistry()
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
    values = {
        "bot_profile_id": "architect-1",
        "organization_id": "org-1",
        "display_name": "Architect",
        "deployment_id": "dep-1",
        "deployment_revision": 1,
        "prompt_version": "v1",
        "capabilities": ("architecture.design",),
    }
    first_inside_store = Event()
    release_first = Event()
    second_started = Event()
    real_add = catalog.add_profile
    calls = 0

    def interleaved_add(value):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_inside_store.set()
            assert release_first.wait(2)
            raise RuntimeError("first persistence failed")
        return real_add(value)

    monkeypatch.setattr(catalog, "add_profile", interleaved_add)
    outcomes = []

    def create(*, signal_started=False):
        if signal_started:
            second_started.set()
        try:
            outcomes.append(service.create_profile(**values))
        except RuntimeError as exc:
            outcomes.append(exc)

    first_thread = Thread(target=create)
    second_thread = Thread(target=create, kwargs={"signal_started": True})
    first_thread.start()
    assert first_inside_store.wait(2)
    second_thread.start()
    assert second_started.wait(2)
    release_first.set()
    first_thread.join(2)
    second_thread.join(2)

    assert any(isinstance(value, RuntimeError) for value in outcomes)
    profile = next(value for value in outcomes if isinstance(value, BotProfile))
    assert registry.get(AgentIdentity(profile.agent_identity)).active is True
    assert catalog.get_profile("org-1", "architect-1") == profile
