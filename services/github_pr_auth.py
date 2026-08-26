"""Authentication boundary for the GitHub PR integration."""

from __future__ import annotations

import time
from typing import Any

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from services.github_pr_contracts import (
    AuthenticationError,
    AuthMethod,
    GitHubAPIError,
)

GITHUB_API_BASE = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_APP_ACCEPT = "application/vnd.github+json"
DEFAULT_TIMEOUT_SECONDS = 30


class GitHubAuthenticator:
    """Resolve token or GitHub App credentials into API request headers."""

    def __init__(
        self,
        *,
        token: str | None = None,
        app_id: str | None = None,
        private_key: str | None = None,
        installation_id: str | None = None,
    ) -> None:
        self._token = token
        self._app_id = app_id
        self._private_key_pem = private_key
        self._installation_id = installation_id
        if not (token or (app_id and private_key)):
            raise AuthenticationError(
                "Either token or app credentials must be provided"
            )

    def get_auth_method(self) -> AuthMethod:
        """Return the configured authentication strategy."""
        return AuthMethod.TOKEN if self._token else AuthMethod.APP

    def get_access_token(self) -> str:
        """Return the token used for API requests."""
        if self._token:
            return self._token
        if not self._app_id or not self._private_key_pem:
            raise AuthenticationError("App credentials not configured")
        if not self._installation_id:
            raise AuthenticationError("Installation ID required for GitHub App auth")

        token_url = (
            f"{GITHUB_API_BASE}/app/installations/{self._installation_id}/access_tokens"
        )
        response = requests.post(
            token_url,
            headers={
                "Authorization": f"Bearer {self._generate_app_jwt()}",
                "Accept": GITHUB_APP_ACCEPT,
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if response.status_code != 201:
            raise GitHubAPIError(
                f"Failed to get installation token: {response.text}",
                response.status_code,
                response.json() if response.text else None,
            )
        return response.json()["token"]

    def _generate_app_jwt(self) -> str:
        """Generate a short-lived GitHub App JWT."""
        try:
            import jwt
        except ImportError as exc:
            raise AuthenticationError(
                "PyJWT library required for GitHub App authentication. "
                "Install with: pip install PyJWT"
            ) from exc

        now = int(time.time())
        payload: dict[str, Any] = {
            "iat": now,
            "exp": now + 600,
            "iss": self._app_id,
        }
        try:
            private_key = serialization.load_pem_private_key(
                self._private_key_pem.encode()
                if isinstance(self._private_key_pem, str)
                else self._private_key_pem,
                password=None,
                backend=default_backend(),
            )
        except ValueError as exc:
            raise AuthenticationError(f"Invalid private key format: {exc}") from exc
        return jwt.encode(payload, private_key, algorithm="RS256")

    def get_headers(
        self,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Build authenticated GitHub API headers."""
        headers = {
            "Authorization": f"token {self.get_access_token()}",
            "Accept": GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if extra_headers:
            headers.update(extra_headers)
        return headers


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "GITHUB_API_BASE",
    "GITHUB_API_VERSION",
    "GITHUB_APP_ACCEPT",
    "GitHubAuthenticator",
]
