from pathlib import Path

from dashboard.multi_bot_control_plane import (
    _get,
    _post,
    _put,
    build_allocation_payload,
    build_connection_payload,
    build_deployment_payload,
    build_profile_payload,
    build_role_payload,
)
from services.bot_provider_credentials import credential_reference

SOURCE = Path("dashboard/multi_bot_control_plane.py")


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        return {"ok": True}

    def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        return {"ok": True}

    def put(self, path, **kwargs):
        self.calls.append(("PUT", path, kwargs))
        return {"ok": True}


def test_get_scopes_request_with_canonical_client():
    client = FakeClient()

    assert _get(client, "org-1", "/resource") == {"ok": True}
    assert client.calls == [
        ("GET", "/resource", {"params": {"organization_id": "org-1"}})
    ]


def test_post_scopes_request_and_uses_json_payload():
    client = FakeClient()
    payload = {"command_id": "cmd-1"}

    assert _post(client, "org-1", "/resource", payload) == {"ok": True}
    assert client.calls == [
        (
            "POST",
            "/resource",
            {
                "params": {"organization_id": "org-1"},
                "json": payload,
            },
        )
    ]


def test_credential_put_uses_write_only_json_payload():
    client = FakeClient()

    assert _put(client, "/credential", {"api_key": "secret"}) == {"ok": True}
    assert client.calls == [("PUT", "/credential", {"json": {"api_key": "secret"}})]


def test_connection_builder_passes_only_opaque_secret_reference_to_bot_catalog():
    reference = credential_reference("openai-prod")
    payload = build_connection_payload(
        connection_id=" openai-prod ",
        brand="OpenAI",
        adapter_type="openai",
        endpoint="https://api.openai.com/v1",
        secret_reference=reference,
        region="eu",
        data_boundary="eu",
        concurrency_limit=2,
    )

    assert payload["connection_id"] == "openai-prod"
    assert payload["secret_reference"] == reference
    assert reference.startswith("dor-runtime-settings://")
    assert "api_key" not in payload
    assert "secret" not in payload


def test_deployment_builder_binds_exact_connection_version():
    payload = build_deployment_payload(
        deployment_id=" gpt-prod ",
        connection_id=" openai-prod ",
        connection_version=3,
        model_id=" gpt-5.6 ",
        model_family=" gpt-5 ",
        max_context_tokens=128000,
        max_output_tokens=8192,
        structured_output=True,
        tool_capabilities=[" code ", "code", ""],
    )

    assert payload["deployment_id"] == "gpt-prod"
    assert payload["connection_id"] == "openai-prod"
    assert payload["connection_version"] == 3
    assert payload["model_id"] == "gpt-5.6"
    assert payload["tool_capabilities"] == ["code"]
    assert payload["command_id"].startswith("dashboard-deployment-")


def test_profile_builder_leaves_ai1_identity_to_the_server():
    payload = build_profile_payload(
        bot_profile_id="architect-primary",
        display_name="Architect",
        deployment_id="mistral-large",
        deployment_revision=1,
        prompt_version="v1",
        capabilities=["architecture.propose"],
    )

    assert "agent_identity" not in payload
    assert payload["capabilities"] == ["architecture.propose"]


def test_role_builder_uses_provider_neutral_role_contract():
    payload = build_role_payload(
        role_id=" chief-architect ",
        name="Chief Architect",
        purpose="Primary architecture",
        protocol_function="proposer",
        required_capabilities=[" architecture.propose ", "architecture.propose"],
        output_schema_ref="schema://architecture/v1",
        rubric_ref="rubric://architecture/v1",
    )

    assert payload["role_id"] == "chief-architect"
    assert payload["protocol_function"] == "proposer"
    assert payload["required_capabilities"] == ["architecture.propose"]
    assert "provider" not in payload
    assert "model" not in payload


def test_allocation_builder_assigns_primary_and_fallback_without_expanding_pool():
    payload = build_allocation_payload(
        allocation_id="architecture-prod",
        role_id="chief-architect",
        role_version=2,
        primary_profile_id="architect-primary",
        primary_profile_version=4,
        fallback_profile_id="architect-fallback",
        fallback_profile_version=7,
        independence_level="provider",
        autonomy_level=2,
        approved_by="admin",
    )

    assert payload["role_id"] == "chief-architect"
    assert payload["role_version"] == 2
    assert payload["members"] == [
        {
            "bot_profile_id": "architect-primary",
            "bot_profile_version": 4,
            "preference_rank": 1,
            "fallback_rank": None,
        },
        {
            "bot_profile_id": "architect-fallback",
            "bot_profile_version": 7,
            "preference_rank": 2,
            "fallback_rank": 1,
        },
    ]


def test_normal_bot_admin_has_no_raw_json_editor_or_secret_reference_field():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'st.text_area("Payload"' not in source
    assert '"Allocation payload"' not in source
    assert '"Selection payload"' not in source
    assert "json.loads" not in source
    assert 'st.text_input("secret_reference"' not in source
    assert 'st.text_input("Secret reference"' not in source
    assert '"API-nøgle"' in source
    assert 'type="password"' in source
    assert '"Gem forbindelse"' in source


def test_bot_admin_exposes_human_facing_setup_and_role_assignment():
    source = SOURCE.read_text(encoding="utf-8")

    for label in (
        "AI-forbindelser",
        "Tilføj AI-forbindelse",
        "Udbyder",
        "API endpoint",
        "API-nøgle",
        "Modeller",
        "AI-bots",
        "Roller & tildeling",
        "Primær AI-bot",
        "Fallback AI-bot",
        "Gem tildeling",
        "Aktivér AI-bot",
    ):
        assert label in source


def test_bot_activation_uses_canonical_endpoint_without_identity_input():
    source = SOURCE.read_text(encoding="utf-8")

    assert "{resource_path('profiles')}/{profile['bot_profile_id']}/activate" in source
    assert '"command_id": f"dashboard-profile-activate-' in source
    assert "agent_identity" not in source
