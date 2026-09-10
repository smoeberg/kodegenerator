from dashboard.admin_access import (
    fetch_organization_admin_status,
    resolve_organization_admin_status,
)


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, path, **kwargs):
        self.calls.append((path, kwargs))
        return self.payload


def test_admin_status_requires_explicit_true_for_selected_organization() -> None:
    payload = {"organizations": [{"id": "org-a", "name": "Alpha", "is_admin": True}, {"id": "org-b", "name": "Beta", "is_admin": False}]}
    assert resolve_organization_admin_status(payload, "org-a") is True
    assert resolve_organization_admin_status(payload, "org-b") is False


def test_missing_or_malformed_admin_status_fails_closed() -> None:
    assert resolve_organization_admin_status({}, "org-a") is None
    assert resolve_organization_admin_status({"organizations": [{"id": "org-a", "name": "Alpha"}]}, "org-a") is None
    assert resolve_organization_admin_status({"organizations": [{"id": "org-a", "is_admin": "true"}]}, "org-a") is None
    assert resolve_organization_admin_status({"organizations": [{"id": "org-b", "is_admin": True}]}, "org-a") is None


def test_admin_status_is_refreshed_from_canonical_backend_catalog() -> None:
    client = FakeClient({"organizations": [{"id": "org-a", "name": "Alpha", "is_admin": True}]})
    assert fetch_organization_admin_status(client, "org-a") is True
    assert client.calls == [("/api/v1/control-plane/organizations", {})]
