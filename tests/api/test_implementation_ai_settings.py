"""Contracts for GUI-managed implementation-AI runtime settings."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from api import dependencies
from api.auth import User
from api.endpoints.integrations import (
    ImplementationAIConfigRequest,
    get_implementation_ai_config,
    put_implementation_ai_config,
)
from domain.actor import Actor, ActorType
from domain.organization import Organization
from infrastructure.persistence.models import OrganizationMembershipModel
from runtime.core import DORRuntime
from services.implementation_ai_settings import (
    effective_implementation_ai_config,
    probe_implementation_ai,
)


@pytest.fixture
def runtime(tmp_path, monkeypatch) -> DORRuntime:
    monkeypatch.setenv("DOR_SETTINGS_ENCRYPTION_KEY", "test-settings-root")
    database_path = tmp_path / "ai-settings.db"
    value = DORRuntime(f"sqlite:///{database_path}")
    value.boot()
    value.create_organization(Organization(id="org-a", name="Alpha"))
    value.register_actor(
        Actor(id="alice", type=ActorType.HUMAN, identity="alice"),
        organization_id="org-a",
    )
    now = datetime.now(timezone.utc)
    with value.database.session() as session:
        session.add(
            OrganizationMembershipModel(
                username="alice",
                organization_id="org-a",
                is_admin=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()
    return value


def _user(username: str = "alice") -> User:
    return User(
        username=username,
        organization_id="org-a",
        full_name="AI Admin",
    )


def _save_ai(runtime: DORRuntime) -> None:
    put_implementation_ai_config(
        ImplementationAIConfigRequest(
            organization_id="org-a",
            model="gpt-saved",
            base_url="https://ai.example.test/v1",
            api_key="saved-key",
        ),
        current_user=_user(),
        dor=runtime,
    )


def test_ai_settings_are_encrypted_and_never_echoed(runtime: DORRuntime) -> None:
    saved = put_implementation_ai_config(
        ImplementationAIConfigRequest(
            organization_id="org-a",
            model="gpt-test",
            base_url="https://ai.example.test/v1",
            api_key="secret-api-key",
        ),
        current_user=_user(),
        dor=runtime,
    )

    assert saved.model == "gpt-test"
    assert saved.base_url == "https://ai.example.test/v1"
    assert saved.api_key_configured is True
    assert saved.active_for_new_tasks is True
    assert "api_key" not in saved.model_dump()

    public = get_implementation_ai_config(
        "org-a",
        current_user=_user(),
        dor=runtime,
    )
    assert public.source == "database"
    assert "api_key" not in public.model_dump()

    internal = effective_implementation_ai_config(runtime.database, "org-a")
    assert internal["api_key"] == "secret-api-key"


def test_ai_settings_require_organization_admin(runtime: DORRuntime) -> None:
    runtime.register_actor(
        Actor(id="bob", type=ActorType.HUMAN, identity="bob"),
        organization_id="org-a",
    )
    now = datetime.now(timezone.utc)
    with runtime.database.session() as session:
        session.add(
            OrganizationMembershipModel(
                username="bob",
                organization_id="org-a",
                is_admin=False,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    with pytest.raises(HTTPException) as exc_info:
        put_implementation_ai_config(
            ImplementationAIConfigRequest(
                organization_id="org-a",
                model="gpt-test",
                base_url="https://ai.example.test/v1",
                api_key="secret-api-key",
            ),
            current_user=_user("bob"),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403


def test_worker_runtime_resolves_saved_tenant_ai_settings(
    runtime: DORRuntime,
    monkeypatch,
) -> None:
    _save_ai(runtime)
    monkeypatch.setenv("DOR_RUNTIME_ROLE", "worker")
    monkeypatch.setenv("DOR_PIPELINE_STATE_ORGANIZATION_ID", "org-a")
    monkeypatch.setenv("OPENAI_API_KEY", "legacy-key")
    monkeypatch.setenv("DOR_IMPLEMENTATION_MODEL", "legacy-model")
    monkeypatch.setenv(
        "DOR_IMPLEMENTATION_OPENAI_BASE_URL", "https://legacy.example.test/v1"
    )
    monkeypatch.setattr(dependencies, "get_dor", lambda: runtime)

    api_key, model, base_url = dependencies._implementation_provider_config()

    assert api_key == "saved-key"
    assert model == "gpt-saved"
    assert base_url == "https://ai.example.test/v1"


def test_api_runtime_does_not_consume_fixed_pipeline_tenant_settings(
    runtime: DORRuntime,
    monkeypatch,
) -> None:
    _save_ai(runtime)
    monkeypatch.setenv("DOR_RUNTIME_ROLE", "api")
    monkeypatch.setenv("DOR_PIPELINE_STATE_ORGANIZATION_ID", "org-a")
    monkeypatch.setenv("OPENAI_API_KEY", "api-env-key")
    monkeypatch.setenv("DOR_IMPLEMENTATION_MODEL", "api-env-model")
    monkeypatch.setenv(
        "DOR_IMPLEMENTATION_OPENAI_BASE_URL", "https://api-env.example.test/v1"
    )
    monkeypatch.setattr(dependencies, "get_dor", lambda: runtime)

    api_key, model, base_url = dependencies._implementation_provider_config()

    assert api_key == "api-env-key"
    assert model == "api-env-model"
    assert base_url == "https://api-env.example.test/v1"


class _ProbeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _size: int) -> bytes:
        return json.dumps({"data": [{"id": "gpt-saved"}]}).encode("utf-8")


def test_connection_probe_checks_model_catalog_without_generation() -> None:
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return _ProbeResponse()

    result = probe_implementation_ai(
        {
            "api_key": "secret",
            "model": "gpt-saved",
            "base_url": "https://ai.example.test/v1",
        },
        opener=opener,
    )

    assert captured["url"] == "https://ai.example.test/v1/models"
    assert result == {
        "configured": True,
        "reachable": True,
        "authenticated": True,
        "model_available": True,
        "error": None,
    }
