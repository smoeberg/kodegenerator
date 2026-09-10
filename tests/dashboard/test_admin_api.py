from __future__ import annotations

from typing import Any

from dashboard.admin_api import AdminAPI, CAPABILITIES


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        self.calls.append((method, path, kwargs))
        return {"ok": True}

    def health(self):
        return self._call("GET", "/health")

    def readiness(self):
        return self._call("GET", "/health/ready")

    def get(self, path: str, **kwargs: Any):
        return self._call("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any):
        return self._call("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any):
        return self._call("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any):
        return self._call("PATCH", path, **kwargs)


def test_admin_facade_uses_canonical_organization_and_user_contracts() -> None:
    client = FakeClient()
    admin = AdminAPI(client)  # type: ignore[arg-type]

    admin.organizations()
    admin.projects("org-a")
    admin.users("org-a")
    admin.create_user(
        "org-a",
        username="alice",
        password="twelve-characters",
        email="a@example.test",
        full_name="Alice",
        is_admin=True,
    )

    assert client.calls[0][:2] == ("GET", "/api/v1/control-plane/organizations")
    assert client.calls[1] == (
        "GET",
        "/api/v1/control-plane/projects",
        {"params": {"organization_id": "org-a"}},
    )
    assert client.calls[2][:2] == (
        "GET",
        "/api/v1/control-plane/organizations/org-a/users",
    )
    assert client.calls[3][0:2] == (
        "POST",
        "/api/v1/control-plane/organizations/org-a/users",
    )
    assert client.calls[3][2]["json"]["is_admin"] is True


def test_empty_replacement_secret_is_not_sent() -> None:
    client = FakeClient()
    admin = AdminAPI(client)  # type: ignore[arg-type]

    admin.save_redmine(
        "org-a",
        url="https://redmine.example.test",
        project_id="alpha",
        api_key=None,
    )
    admin.save_ai(
        "org-a",
        model="model-a",
        base_url="https://ai.example.test/v1",
        api_key=None,
    )

    redmine_payload = client.calls[0][2]["json"]
    ai_payload = client.calls[1][2]["json"]
    assert "api_key" not in redmine_payload
    assert "api_key" not in ai_payload
    assert redmine_payload["organization_id"] == "org-a"
    assert ai_payload["organization_id"] == "org-a"


def test_integration_tests_are_tenant_scoped() -> None:
    client = FakeClient()
    admin = AdminAPI(client)  # type: ignore[arg-type]

    admin.test_redmine("org-a")
    admin.test_ai("org-a")

    assert client.calls == [
        (
            "POST",
            "/api/v1/integrations/redmine/test",
            {"params": {"organization_id": "org-a"}},
        ),
        (
            "POST",
            "/api/v1/integrations/ai/test",
            {"params": {"organization_id": "org-a"}},
        ),
    ]


def test_capability_map_does_not_claim_missing_backend_contracts() -> None:
    support = {item.key: item.support for item in CAPABILITIES}

    assert support["organizations"] == "implemented"
    assert support["users"] == "implemented"
    assert support["redmine"] == "implemented"
    assert support["audit"] == "unsupported"
    assert support["departments"] == "unsupported"
    assert support["repository_mapping"] == "unsupported"
    assert support["notifications"] == "unsupported"
