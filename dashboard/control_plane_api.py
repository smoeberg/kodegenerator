"""Small, strict HTTP client for the governed multi-bot control plane."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ControlPlaneAPIError(RuntimeError):
    """Raised when the control plane cannot satisfy a dashboard request."""


@dataclass(frozen=True)
class ControlPlaneAPI:
    base_url: str
    token: str
    organization_id: str
    timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("DOR API base URL must use HTTP or HTTPS")
        if not self.token.strip():
            raise ValueError("A bearer token is required for the governed dashboard")
        if not self.organization_id.strip():
            raise ValueError("An organization ID is required")

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        separator = "&" if "?" in path else "?"
        url = (
            f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
            f"{separator}{urlencode({'organization_id': self.organization_id})}"
        )
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            url,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                **({"Content-Type": "application/json"} if body else {}),
            },
        )
        try:
            # The constructor rejects every scheme except HTTP(S) before this call.
            with urlopen(request, timeout=self.timeout_seconds) as response:  # nosec B310
                raw = response.read()
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ControlPlaneAPIError(
                f"Control Plane returned HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise ControlPlaneAPIError(f"Control Plane is unavailable: {exc}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ControlPlaneAPIError("Control Plane returned invalid JSON") from exc


RESOURCE_PATHS = {
    "connections": "/api/v1/bot-governance/connections",
    "deployments": "/api/v1/bot-governance/deployments",
    "profiles": "/api/v1/bot-governance/profiles",
    "roles": "/api/v1/bot-governance/roles",
    "templates": "/api/v1/bot-governance/templates",
}

CREATE_EXAMPLES: dict[str, dict[str, Any]] = {
    "connections": {
        "command_id": "configure-connection-001",
        "connection_id": "connection-mistral-eu-1",
        "brand": "mistral",
        "adapter_type": "mistral_api",
        "endpoint": "https://api.mistral.ai/v1",
        "secret_reference": "secret://providers/mistral/eu-1",
        "region": "eu",
        "data_boundary": "eu",
        "concurrency_limit": 6,
        "enabled": True,
    },
    "deployments": {
        "command_id": "configure-deployment-001",
        "deployment_id": "mistral-large-eu-1",
        "connection_id": "connection-mistral-eu-1",
        "connection_version": 1,
        "model_id": "mistral-large-latest",
        "model_family": "mistral-large",
        "max_context_tokens": 128000,
        "max_output_tokens": 8192,
        "structured_output": True,
        "tool_capabilities": [],
    },
    "profiles": {
        "command_id": "configure-profile-001",
        "bot_profile_id": "architect-mistral-1",
        "agent_identity": "agent.architect.mistral.1",
        "display_name": "Architecture Bot 1",
        "deployment_id": "mistral-large-eu-1",
        "deployment_revision": 1,
        "prompt_version": "architect-v1",
        "capabilities": ["architecture.propose"],
        "permitted_tools": [],
        "data_policy": {
            "boundary": "eu",
            "allowed_regions": ["eu"],
            "source_code_allowed": True,
        },
        "budget_policy": {
            "max_cost_minor_units": 500,
            "max_input_tokens": 32000,
            "max_output_tokens": 4096,
        },
        "concurrency_limit": 1,
        "enabled": False,
    },
    "roles": {
        "command_id": "configure-role-001",
        "role_id": "chief-architect",
        "name": "Chief Architect",
        "purpose": "Create the primary architecture proposal",
        "protocol_function": "proposal",
        "required_capabilities": ["architecture.propose"],
        "output_schema_ref": "schema://architecture/proposal/v1",
        "rubric_ref": "rubric://architecture/v1",
        "independent_verification": True,
        "enabled": True,
    },
    "templates": {
        "command_id": "configure-template-001",
        "template_id": "architecture-council",
        "name": "Architecture council",
        "stages": [
            {
                "stage_id": "proposal",
                "protocol_function": "proposal",
                "role_versions": [["chief-architect", 1]],
                "minimum_assignments": 1,
                "maximum_assignments": 1,
                "parallel": False,
                "blocking": True,
            }
        ],
        "approved_by": "controller",
        "enabled": True,
    },
}


def resource_path(resource: str) -> str:
    try:
        return RESOURCE_PATHS[resource]
    except KeyError as exc:
        raise ValueError(f"Unsupported dashboard resource: {resource}") from exc
