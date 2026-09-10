from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

import dashboard.api_client as api_client_module
import dashboard.multi_bot_control_plane as multi_bot_module

APP_PATH = Path(__file__).resolve().parents[2] / "dashboard" / "operator_center.py"


class FakeAPI:
    def __init__(self, *, is_admin: Any) -> None:
        self.is_admin = is_admin
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def login(self, username: str, password: str) -> str:
        self.calls.append(("LOGIN", username, {"password": password}))
        return "token"

    def health(self) -> dict[str, str]:
        self.calls.append(("GET", "/health", {}))
        return {"status": "ok"}

    def readiness(self) -> dict[str, str]:
        self.calls.append(("GET", "/health/ready", {}))
        return {"status": "ready", "migration_head": "036_runtime_settings"}

    def get(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("GET", path, kwargs))
        if path == "/api/v1/control-plane/organizations":
            item = {"id": "org-a", "name": "Alpha", "description": ""}
            if self.is_admin != "missing":
                item["is_admin"] = self.is_admin
            return {"active_organization_id": "org-a", "organizations": [item]}
        if path == "/api/v1/control-plane/projects":
            return {"organization_id": "org-a", "projects": []}
        if path == "/api/v1/execution":
            return []
        if path == "/api/v1/control-plane/organizations/org-a/users":
            return []
        if path == "/api/v1/integrations/redmine/config":
            return {"organization_id": "org-a", "url": "https://redmine.example.test", "project_id": "alpha", "api_key_configured": True, "source": "database"}
        if path == "/api/v1/integrations/ai/config":
            return {"organization_id": "org-a", "provider": "openai_compatible", "model": "model-a", "base_url": "https://ai.example.test/v1", "api_key_configured": True, "source": "database", "active_for_new_tasks": True, "applies_to": "new_tasks"}
        raise AssertionError(f"unexpected GET {path}")

    def post(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("POST", path, kwargs))
        return {"ok": True}

    def put(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("PUT", path, kwargs))
        return kwargs.get("json", {})

    def patch(self, path: str, **kwargs: Any) -> Any:
        self.calls.append(("PATCH", path, kwargs))
        if path == "/api/v1/control-plane/organizations/org-a":
            return {"id": "org-a", "name": kwargs["json"]["name"], "description": ""}
        return {"username": path.rsplit("/", 1)[-1]}


@pytest.fixture
def install_fake(monkeypatch: pytest.MonkeyPatch):
    def factory(*, is_admin: Any):
        client = FakeAPI(is_admin=is_admin)
        monkeypatch.setattr(api_client_module, "DORAPIClient", lambda *args, **kwargs: client)
        monkeypatch.setattr(multi_bot_module, "render_multi_bot_control_plane", lambda *args, **kwargs: None)
        return client
    return factory


def _run() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=8)
    at.session_state["access_token"] = "existing-token"
    at.session_state["username"] = "alice"
    at.session_state["organization_id"] = "org-a"
    return at.run(timeout=8)


def _button(at: AppTest, label: str):
    matches = [item for item in at.button if item.label == label]
    assert len(matches) == 1, f"expected one button {label!r}, got {len(matches)}"
    return matches[0]


def test_admin_login_context_exposes_integrated_administration_and_scoped_mutation(install_fake) -> None:
    client = install_fake(is_admin=True)
    at = _run()
    assert len(at.sidebar.radio) == 2
    assert at.sidebar.radio[1].label == "Administration"
    at = at.sidebar.radio[1].set_value("Administration").run(timeout=8)
    assert any("Administration" in str(item.value) for item in at.markdown)
    at = _button(at, "Gem organisation").click().run(timeout=8)
    assert any(method == "PATCH" and path == "/api/v1/control-plane/organizations/org-a" for method, path, _ in client.calls)


def test_non_admin_has_no_administration_navigation(install_fake) -> None:
    install_fake(is_admin=False)
    at = _run()
    assert len(at.sidebar.radio) == 1
    assert all(item.label != "Administration" for item in at.sidebar.radio)


def test_missing_admin_status_fails_closed_in_operator_navigation(install_fake) -> None:
    install_fake(is_admin="missing")
    at = _run()
    assert len(at.sidebar.radio) == 1
    captions = [item.value for item in at.sidebar.caption]
    assert "Status kan ikke fastslås" in captions
