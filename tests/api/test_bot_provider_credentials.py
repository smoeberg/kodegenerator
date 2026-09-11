"""Security contracts for tenant-scoped AI provider credentials."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from api.auth import User
from api.endpoints.control_plane_organizations import (
    BotProviderCredentialRequest,
    get_bot_provider_credential_status,
    put_bot_provider_credential,
)
from domain.actor import Actor, ActorType
from domain.organization import Organization
from infrastructure.persistence.models import OrganizationMembershipModel
from phase4.agent_registry.bot_profiles import ProviderConnection
from runtime.core import DORRuntime
from services.bot_provider_credentials import (
    BotProviderCredentialStore,
    credential_reference,
    credential_setting_key,
)


@pytest.fixture
def runtime(tmp_path, monkeypatch: pytest.MonkeyPatch) -> DORRuntime:
    monkeypatch.setenv("DOR_ENCRYPTION_KEY", "credential-test-root-key")
    value = DORRuntime(f"sqlite:///{tmp_path / 'bot-credentials.db'}")
    value.boot()
    return value


def _seed_org(
    runtime: DORRuntime,
    *,
    organization_id: str,
    username: str,
    is_admin: bool,
) -> None:
    runtime.create_organization(
        Organization(id=organization_id, name=f"Organization {organization_id}")
    )
    runtime.register_actor(
        Actor(id=username, type=ActorType.HUMAN, identity=username),
        organization_id=organization_id,
    )
    now = datetime.now(timezone.utc)
    with runtime.database.session() as session:
        session.add(
            OrganizationMembershipModel(
                username=username,
                organization_id=organization_id,
                is_admin=is_admin,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def _user(username: str = "alice", organization_id: str = "org-a") -> User:
    return User(username=username, organization_id=organization_id, full_name=username)


def test_authorized_admin_writes_encrypted_credential_and_api_never_returns_key(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)
    raw_key = "sk-live-super-secret-value"

    result = put_bot_provider_credential(
        "org-a",
        "openai-production",
        BotProviderCredentialRequest(api_key=raw_key),
        current_user=_user(),
        dor=runtime,
    )
    public = result.model_dump()

    assert public["credential_configured"] is True
    assert public["secret_reference"] == credential_reference("openai-production")
    assert "api_key" not in public
    assert raw_key not in repr(public)

    with runtime.database.session("org-a") as session:
        row = session.execute(
            text(
                "SELECT value_json, secret_ciphertext FROM runtime_settings "
                "WHERE organization_id = :organization_id AND setting_key = :setting_key"
            ),
            {
                "organization_id": "org-a",
                "setting_key": credential_setting_key("openai-production"),
            },
        ).mappings().one()
    assert row["secret_ciphertext"]
    assert row["secret_ciphertext"] != raw_key
    assert raw_key not in row["secret_ciphertext"]
    assert raw_key not in row["value_json"]
    assert (
        BotProviderCredentialStore(runtime.database).secret(
            "org-a", "openai-production"
        )
        == raw_key
    )


def test_provider_connection_receives_only_opaque_secret_reference(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)
    raw_key = "sk-provider-only-write"
    result = put_bot_provider_credential(
        "org-a",
        "openai-production",
        BotProviderCredentialRequest(api_key=raw_key),
        current_user=_user(),
        dor=runtime,
    )
    reference = result.secret_reference
    assert reference is not None
    assert reference.startswith("dor-runtime-settings://")
    assert raw_key not in reference

    connection = ProviderConnection(
        connection_id="openai-production",
        organization_id="org-a",
        brand="OpenAI",
        adapter_type="openai",
        endpoint="https://api.openai.com/v1",
        secret_reference=reference,
    )
    assert connection.secret_reference == reference
    assert connection.secret_reference != raw_key


def test_non_admin_credential_write_is_denied(runtime: DORRuntime) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=False)

    with pytest.raises(HTTPException) as exc_info:
        put_bot_provider_credential(
            "org-a",
            "openai-production",
            BotProviderCredentialRequest(api_key="sk-denied"),
            current_user=_user(),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403


def test_admin_cannot_write_credential_across_tenant_boundary(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)
    _seed_org(runtime, organization_id="org-b", username="bob", is_admin=True)

    with pytest.raises(HTTPException) as exc_info:
        put_bot_provider_credential(
            "org-b",
            "openai-production",
            BotProviderCredentialRequest(api_key="sk-cross-tenant"),
            current_user=_user(organization_id="org-a"),
            dor=runtime,
        )

    assert exc_info.value.status_code == 403


def test_credential_status_exposes_only_boolean_state_and_opaque_reference(
    runtime: DORRuntime,
) -> None:
    _seed_org(runtime, organization_id="org-a", username="alice", is_admin=True)

    missing = get_bot_provider_credential_status(
        "org-a",
        "openai-production",
        current_user=_user(),
        dor=runtime,
    ).model_dump()
    assert set(missing) == {
        "organization_id",
        "connection_id",
        "credential_configured",
        "secret_reference",
    }
    assert missing["credential_configured"] is False
    assert missing["secret_reference"] is None

    put_bot_provider_credential(
        "org-a",
        "openai-production",
        BotProviderCredentialRequest(api_key="sk-status-only"),
        current_user=_user(),
        dor=runtime,
    )
    configured = get_bot_provider_credential_status(
        "org-a",
        "openai-production",
        current_user=_user(),
        dor=runtime,
    ).model_dump()
    assert configured["credential_configured"] is True
    assert configured["secret_reference"] == credential_reference("openai-production")
    assert "sk-status-only" not in repr(configured)


def test_runtime_settings_encryption_and_rls_contract_remains_canonical() -> None:
    settings_source = Path("services/runtime_settings.py").read_text(encoding="utf-8")
    migration_source = Path("alembic/versions/036_runtime_settings.py").read_text(
        encoding="utf-8"
    )

    assert "encrypt_secret(secret)" in settings_source
    assert "with self._database.session(organization_id) as session:" in settings_source
    assert 'ALTER TABLE "runtime_settings" ENABLE ROW LEVEL SECURITY' in migration_source
    assert 'ALTER TABLE "runtime_settings" FORCE ROW LEVEL SECURITY' in migration_source
    assert "dor.organization_id" in migration_source
