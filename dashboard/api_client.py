"""Small, tenant-aware HTTP client used by the Streamlit control plane.

The dashboard is deliberately a thin client: domain rules, authorization and
state transitions stay in FastAPI. This module owns transport concerns only.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests


STREAM_SESSION_COOKIE = "eiraos_execution_stream"


class DORAPIError(RuntimeError):
    """Raised for an API response that cannot be used by the GUI."""

    def __init__(self, status_code: int, message: str, payload: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class DORAPIClient:
    def __init__(self, base_url: str | None = None, token: str | None = None, timeout: float = 15.0):
        self.base_url = (base_url or os.getenv("DOR_API_URL", "http://api:8000")).rstrip("/")
        self.token = token
        self.timeout = timeout
        self.session = requests.Session()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                json: Any = None, data: Any = None, timeout: float | None = None) -> Any:
        response = self.session.request(
            method,
            f"{self.base_url}/{path.lstrip('/')}",
            headers=self._headers(),
            params=params,
            json=json,
            data=data,
            timeout=timeout or self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        if response.status_code == 401:
            raise DORAPIError(401, "API session expired or is invalid", payload)
        if not response.ok:
            message = payload.get("detail", payload) if isinstance(payload, dict) else payload
            raise DORAPIError(response.status_code, str(message), payload)
        return payload

    def health(self) -> Any:
        return self.request("GET", "/health")

    def readiness(self) -> Any:
        return self.request("GET", "/health/ready")

    def protected(self) -> Any:
        return self.request("GET", "/protected")

    def login(self, username: str, password: str) -> str:
        response = self.session.post(
            f"{self.base_url}/auth/token",
            data={"username": username, "password": password},
            headers={"Accept": "application/json"},
            timeout=self.timeout,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = response.text
        if not response.ok:
            message = payload.get("detail", payload) if isinstance(payload, dict) else payload
            raise DORAPIError(response.status_code, str(message), payload)
        token = payload.get("access_token")
        if not token:
            raise DORAPIError(response.status_code, "Token response did not contain access_token", payload)
        self.token = token
        return token

    def create_stream_session(self, workflow_id: str) -> dict[str, Any]:
        """Create the workflow-scoped HttpOnly cookie used by browser transports."""
        return self.request("POST", f"/api/v1/execution/stream-session/{workflow_id}")

    def delete_stream_session(self, workflow_id: str) -> None:
        try:
            self.request("DELETE", f"/api/v1/execution/stream-session/{workflow_id}")
        except DORAPIError as exc:
            if exc.status_code != 404:
                raise

    def stream_url(self, workflow_id: str, *, websocket: bool) -> str:
        path = f"/api/v1/execution/{'ws' if websocket else 'events'}/{workflow_id}"
        parsed = urlparse(f"{self.base_url}{path}")
        if websocket:
            scheme = "wss" if parsed.scheme == "https" else "ws"
            parsed = parsed._replace(scheme=scheme)
        return urlunparse(parsed)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)
