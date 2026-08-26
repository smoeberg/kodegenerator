"""Public compatibility facade for the modular GitHub PR integration.

The implementation is intentionally split by responsibility. Existing imports from
``services.github_pr_bot`` remain stable while auth, REST transport, formatting,
webhooks, and orchestration can be tested independently.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from services.github_pr_api import GitHubAPIClientMixin
from services.github_pr_auth import (
    DEFAULT_TIMEOUT_SECONDS,
    GITHUB_API_BASE,
    GITHUB_API_VERSION,
    GITHUB_APP_ACCEPT,
    GitHubAuthenticator,
)
from services.github_pr_contracts import (
    AppAuthConfig,
    AuthenticationError,
    AuthMethod,
    ChangelogEntry,
    CommitInfo,
    GitHubAPIError,
    GitHubConfig,
    GitHubPRBotError,
    PatchInfo,
    PRAction,
    PRMetadata,
    PRResult,
    PRStatus,
    RateLimitError,
    TokenAuthConfig,
    WebhookEventType,
    WebhookPayload,
    WebhookResponse,
    WebhookVerificationError,
)
from services.github_pr_formatting import GitHubPRFormatter
from services.github_pr_webhooks import (
    GITHUB_WEBHOOK_DELIVERY_HEADER,
    GITHUB_WEBHOOK_EVENT_HEADER,
    GITHUB_WEBHOOK_SIGNATURE_HEADER,
    GitHubPRWebhookMixin,
    WebhookParser,
    WebhookVerifier,
)
from services.github_pr_workflow import GitHubPRWorkflowMixin

DEFAULT_USER_AGENT = "kodegenerator-github-bot/1.0.0"


class GitHubPRBot(
    GitHubAPIClientMixin,
    GitHubPRWorkflowMixin,
    GitHubPRWebhookMixin,
):
    """Compose GitHub PR capabilities behind the historical public interface."""

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        auth_config: TokenAuthConfig | AppAuthConfig,
        webhook_secret: str | None = None,
        config: GitHubConfig | None = None,
        signing_key: bytes | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self.repo_full_name = f"{owner}/{repo}"
        self.config = config or GitHubConfig()
        self.webhook_secret = webhook_secret

        if isinstance(auth_config, TokenAuthConfig):
            self._auth = GitHubAuthenticator(token=auth_config.token)
        elif isinstance(auth_config, AppAuthConfig):
            self._auth = GitHubAuthenticator(
                app_id=auth_config.app_id,
                private_key=auth_config.private_key,
                installation_id=auth_config.installation_id,
            )
        else:
            raise AuthenticationError("Invalid auth configuration type")

        self._signing_key = signing_key or self._load_signing_key()
        self._webhook_verifier = (
            WebhookVerifier(webhook_secret) if webhook_secret else None
        )
        self._formatter = GitHubPRFormatter()

    def _load_signing_key(self) -> bytes:
        """Load the configured HMAC key or create an ephemeral development key."""
        encoded = os.environ.get("GITHUB_BOT_SIGNING_KEY")
        if encoded:
            padded = encoded + "=" * (-len(encoded) % 4)
            try:
                return base64.b64decode(padded, altchars=b"-_", validate=True)
            except (binascii.Error, ValueError) as exc:
                raise GitHubPRBotError("Invalid GITHUB_BOT_SIGNING_KEY") from exc
        return secrets.token_bytes(32)

    def _compute_fingerprint(self, data: dict[str, Any]) -> str:
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _sign_data(self, data: str) -> str:
        return hmac.new(
            self._signing_key, data.encode("utf-8"), hashlib.sha256
        ).hexdigest()


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "DEFAULT_USER_AGENT",
    "GITHUB_API_BASE",
    "GITHUB_API_VERSION",
    "GITHUB_APP_ACCEPT",
    "GITHUB_WEBHOOK_DELIVERY_HEADER",
    "GITHUB_WEBHOOK_EVENT_HEADER",
    "GITHUB_WEBHOOK_SIGNATURE_HEADER",
    "AppAuthConfig",
    "AuthMethod",
    "AuthenticationError",
    "ChangelogEntry",
    "CommitInfo",
    "GitHubAPIError",
    "GitHubAuthenticator",
    "GitHubConfig",
    "GitHubPRBot",
    "GitHubPRBotError",
    "PRAction",
    "PRMetadata",
    "PRResult",
    "PRStatus",
    "PatchInfo",
    "RateLimitError",
    "TokenAuthConfig",
    "WebhookEventType",
    "WebhookParser",
    "WebhookPayload",
    "WebhookResponse",
    "WebhookVerificationError",
    "WebhookVerifier",
]
