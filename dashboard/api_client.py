"""Small, tenant-aware HTTP client used by the Streamlit control plane.

The dashboard is deliberately a thin client: domain rules, authorization and
state transitions stay in FastAPI. This module owns transport concerns only.
"""

from __future__ import annotations

import os
from typing import Any

import requests


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

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)
