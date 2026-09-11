from pathlib import Path

from dashboard.multi_bot_control_plane import (
    _get,
    _post,
    build_allocation_payload,
    build_deployment_payload,
    build_role_payload,
)

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


def test_normal_bot_admin_has_no_raw_json_payload_editor_or_secret_reference_input():
    source = SOURCE.read_text(encoding="utf-8")

    assert 'st.text_area("Payload"' not in source
    assert '"Allocation payload"' not in source
    assert '"Selection payload"' not in source
    assert "json.loads" not in source
    assert "secret_reference" not in source
    assert "API-key onboarding" in source
    assert "secret-manager" in source


def test_bot_admin_exposes_human_facing_setup_and_role_assignment():
    source = SOURCE.read_text(encoding="utf-8")

    for label in (
        "AI-forbindelser",
        "Modeller",
        "AI-bots",
        "Roller & tildeling",
        "Primær AI-bot",
        "Fallback AI-bot",
        "Gem tildeling",
    ):
        assert label in source
