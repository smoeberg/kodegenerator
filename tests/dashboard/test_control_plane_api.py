import json
from urllib.error import HTTPError

import pytest

from api.schemas.bot_governance import (
    ConnectionCreateRequest,
    DeploymentCreateRequest,
    ProfileCreateRequest,
    RoleCreateRequest,
    TemplateCreateRequest,
)
from dashboard.control_plane_api import (
    CREATE_EXAMPLES,
    ControlPlaneAPI,
    ControlPlaneAPIError,
    resource_path,
)


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_client_scopes_request_and_uses_bearer(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured.update(request=request, timeout=timeout)
        return Response([{"connection_id": "one"}])

    monkeypatch.setattr("dashboard.control_plane_api.urlopen", fake_urlopen)
    client = ControlPlaneAPI("https://dor.example", "secret-token", "org-1", 3)

    assert client.get(resource_path("connections")) == [{"connection_id": "one"}]
    assert captured["request"].full_url.endswith("organization_id=org-1")
    assert captured["request"].get_header("Authorization") == "Bearer secret-token"
    assert captured["timeout"] == 3


def test_client_posts_json_without_logging_or_returning_token(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return Response({"enabled": True})

    monkeypatch.setattr("dashboard.control_plane_api.urlopen", fake_urlopen)
    client = ControlPlaneAPI("https://dor.example", "secret-token", "org-1")

    assert client.post("/resource", {"secret_reference": "secret://one"}) == {
        "enabled": True
    }
    assert captured["body"] == {"secret_reference": "secret://one"}


def test_http_failure_is_fail_closed(monkeypatch):
    def fake_urlopen(_request, timeout):
        del timeout
        raise HTTPError("https://dor.example", 403, "denied", {}, None)

    monkeypatch.setattr("dashboard.control_plane_api.urlopen", fake_urlopen)
    client = ControlPlaneAPI("https://dor.example", "token", "org-1")

    with pytest.raises(ControlPlaneAPIError, match="HTTP 403"):
        client.get("/resource")


@pytest.mark.parametrize(
    "base,token,org",
    [("file:///tmp/x", "t", "o"), ("https://x", "", "o"), ("https://x", "t", "")],
)
def test_invalid_connection_configuration_is_rejected(base, token, org):
    with pytest.raises(ValueError):
        ControlPlaneAPI(base, token, org)


def test_unknown_resource_is_rejected():
    with pytest.raises(ValueError, match="Unsupported"):
        resource_path("imaginary")


def test_dashboard_examples_match_versioned_api_contracts():
    schemas = {
        "connections": ConnectionCreateRequest,
        "deployments": DeploymentCreateRequest,
        "profiles": ProfileCreateRequest,
        "roles": RoleCreateRequest,
        "templates": TemplateCreateRequest,
    }
    for resource, schema in schemas.items():
        schema.model_validate(CREATE_EXAMPLES[resource])
