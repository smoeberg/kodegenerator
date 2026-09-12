from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from api.auth import User, get_current_active_user
from api.dependencies import get_bot_catalog_service, get_dor
from api.endpoints import bot_governance
from infrastructure.persistence.bot_catalog_models import (
    BotModelDeploymentModel,
    BotProfileModel,
    BotProviderConnectionModel,
)
from infrastructure.persistence.bot_catalog_store import BotCatalogStore
from phase4.agent_registry import AgentIdentity, AgentRegistry
from phase4.agent_registry.bot_profiles import ModelDeployment, ProviderConnection
from services.bot_catalog import BotCatalogService


def _client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-http.db'}")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    BotProviderConnectionModel.__table__.create(engine)
    BotModelDeploymentModel.__table__.create(engine)
    BotProfileModel.__table__.create(engine)
    store = BotCatalogStore(sessionmaker(bind=engine, expire_on_commit=False))
    registry = AgentRegistry()
    service = BotCatalogService(store, registry)
    service.create_connection(
        ProviderConnection(
            connection_id="shared",
            organization_id="org-1",
            brand="Mistral",
            adapter_type="mistral-api",
            endpoint="https://api.mistral.ai/v1",
            secret_reference="secret://org-1/mistral",
        )
    )
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
    app = FastAPI()
    app.include_router(bot_governance.router)
    app.dependency_overrides[get_current_active_user] = lambda: User(
        username="admin", organization_id="org-1"
    )
    app.dependency_overrides[get_dor] = lambda: object()
    app.dependency_overrides[get_bot_catalog_service] = lambda: service
    monkeypatch.setattr(bot_governance, "_authorize", lambda *args: None)
    return TestClient(app), store, registry


def _payload(**changes):
    return {
        "command_id": "create-profile-1",
        "bot_profile_id": "architect-1",
        "display_name": "Architect",
        "deployment_id": "dep-1",
        "deployment_revision": 1,
        "prompt_version": "v1",
        "capabilities": ["architecture.design"],
        **changes,
    }


def test_post_profile_omits_identity_and_returns_persisted_derived_value(
    tmp_path, monkeypatch
) -> None:
    client, store, registry = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/bot-governance/profiles?organization_id=org-1",
        json=_payload(),
    )

    assert response.status_code == 201, response.text
    identity = response.json()["agent_identity"]
    assert len(identity) == 64
    assert store.get_profile("org-1", "architect-1").agent_identity == identity
    assert registry.get(AgentIdentity(identity)).active is True


def test_post_profile_rejects_supplied_identity_as_extra_input(
    tmp_path, monkeypatch
) -> None:
    client, _, _ = _client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/bot-governance/profiles?organization_id=org-1",
        json=_payload(agent_identity="1" * 64),
    )
    assert response.status_code == 422


def test_post_profile_retry_and_control_errors_are_stable_4xx(
    tmp_path, monkeypatch
) -> None:
    client, _, registry = _client(tmp_path, monkeypatch)
    path = "/api/v1/bot-governance/profiles?organization_id=org-1"
    first = client.post(path, json=_payload())
    assert first.status_code == 201
    assert client.post(path, json=_payload()).json() == first.json()

    conflict = client.post(path, json=_payload(display_name="Different"))
    assert conflict.status_code == 409

    registry.deactivate(AgentIdentity(first.json()["agent_identity"]), actor="test")
    inactive = client.post(path, json=_payload())
    assert inactive.status_code == 422
    invalid = client.post(
        path, json=_payload(bot_profile_id="not valid", capabilities=[])
    )
    assert invalid.status_code == 422
    assert inactive.status_code < 500 and invalid.status_code < 500
