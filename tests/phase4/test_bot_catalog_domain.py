from dataclasses import replace

import pytest

from phase4.agent_registry.bot_profiles import (
    BotProfile,
    ModelDeployment,
    ProviderConnection,
)


def connection(connection_id: str = "mistral-01") -> ProviderConnection:
    return ProviderConnection(
        connection_id=connection_id,
        organization_id="org-1",
        brand="Mistral",
        adapter_type="mistral-api",
        endpoint="https://api.mistral.ai/v1",
        secret_reference=f"secret://org-1/{connection_id}",
    )


def test_same_brand_accounts_remain_distinct_bot_connections() -> None:
    values = [connection(f"mistral-{number:02}") for number in range(1, 7)]
    assert len({value.connection_id for value in values}) == 6
    assert len({value.fingerprint for value in values}) == 6
    assert {value.brand for value in values} == {"Mistral"}


def test_provider_brand_is_open_and_local_http_endpoint_is_supported() -> None:
    value = replace(
        connection(),
        brand="LibreChat Internal",
        adapter_type="openai-compatible",
        endpoint="http://librechat.internal:3080/v1",
    )
    assert value.brand == "LibreChat Internal"


def test_endpoint_credentials_are_rejected() -> None:
    with pytest.raises(ValueError, match="credentials"):
        replace(connection(), endpoint="https://user:password@example.test/v1")


def test_configuration_versions_bind_exact_relationship_versions() -> None:
    deployment = ModelDeployment(
        deployment_id="dep-1",
        organization_id="org-1",
        connection_id="mistral-01",
        connection_version=2,
        model_id="mistral-large",
        model_family="mistral",
        max_context_tokens=128_000,
        max_output_tokens=8_192,
    )
    profile = BotProfile(
        bot_profile_id="profile-1",
        organization_id="org-1",
        agent_identity="1" * 64,
        display_name="Architect",
        deployment_id="dep-1",
        deployment_revision=deployment.revision,
        prompt_version="architect-v1",
        capabilities=("architecture.design",),
    )
    assert deployment.connection_version == 2
    assert profile.deployment_revision == 1
    assert deployment.next_revision(status="disabled").revision == 2


def test_capabilities_must_be_canonical() -> None:
    with pytest.raises(ValueError, match="sorted and unique"):
        BotProfile(
            bot_profile_id="profile-1",
            organization_id="org-1",
            agent_identity="1" * 64,
            display_name="Architect",
            deployment_id="dep-1",
            deployment_revision=1,
            prompt_version="v1",
            capabilities=("z", "a"),
        )
