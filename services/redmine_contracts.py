"""Immutable contracts and public errors for the Redmine issue integration.

The transport layer (:mod:`services.redmine_api`) speaks to a Redmine
REST API; the orchestration adapter (:mod:`services.redmine_error_ticketing`)
maps DOR verification failures (self-healing exhaustion, generation
failures) onto these values. Keeping transport-neutral contracts here
mirrors the GitHub PR integration and keeps the API client testable with
respx/mocks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class RedmineIssueStatus(str, Enum):
    """Redmine issue statuses used by the DOR integration.

    Values are the *default* Redmine status identifiers (1 = new,
    2 = in progress, 3 = resolved, 5 = closed). Projects that renumber
    their tracker states can override them through
    :class:`RedmineConfig`.
    """

    NEW = "1"
    IN_PROGRESS = "2"
    RESOLVED = "3"
    CLOSED = "5"


class RedmineIssuePriority(str, Enum):
    """Default Redmine priority identifiers (1 = low … 5 = urgent)."""

    LOW = "1"
    NORMAL = "2"
    HIGH = "3"
    URGENT = "4"
    IMMEDIATE = "5"


class RedmineErrorKind(str, Enum):
    """High-level classification of the DOR failure being reported."""

    VERIFICATION = "verification"
    GENERATION = "generation"
    SELF_HEALING = "self_healing"
    EXECUTION = "execution"


@dataclass(frozen=True)
class RedmineConfig:
    """Configuration for one Redmine instance.

    ``api_key`` may be an API token (preferred) or a password used
    together with ``username``; the transport sends the appropriate
    header/basic-auth pair.
    """

    url: str
    api_key: str = ""
    username: str = ""
    password: str = ""
    project_id: str = "1"
    tracker_id: str = "1"
    priority_id: str = RedmineIssuePriority.NORMAL.value
    status_id: str = RedmineIssueStatus.NEW.value
    timeout: float = 15.0
    retry_count: int = 2
    retry_delay: float = 1.0
    verify_tls: bool = True

    def validate(self) -> None:
        """Fail fast on obviously unusable configuration."""
        from urllib.parse import urlsplit

        parsed = urlsplit(self.url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Redmine url must use http or https and include a host")
        if not self.api_key and not (self.username and self.password):
            raise ValueError("Redmine requires an api_key or username/password pair")
        if not self.project_id or not self.tracker_id:
            raise ValueError("Redmine requires a project id and tracker id")


@dataclass(frozen=True)
class RedmineIssueDraft:
    """Payload for a new issue, independent of transport details."""

    subject: str
    description: str
    project_id: str = "1"
    tracker_id: str = "1"
    priority_id: str = RedmineIssuePriority.NORMAL.value
    status_id: str = RedmineIssueStatus.NEW.value
    category_id: str | None = None
    assigned_to_id: str | None = None
    custom_fields: tuple[tuple[str, Any], ...] = ()

    def payload(self) -> dict[str, Any]:
        issue: dict[str, Any] = {
            "subject": self.subject,
            "description": self.description,
            "project_id": self.project_id,
            "tracker_id": self.tracker_id,
            "priority_id": self.priority_id,
            "status_id": self.status_id,
        }
        if self.category_id:
            issue["category_id"] = self.category_id
        if self.assigned_to_id:
            issue["assigned_to_id"] = self.assigned_to_id
        if self.custom_fields:
            issue["custom_fields"] = [
                {"id": name, "value": value} for name, value in self.custom_fields
            ]
        return {"issue": issue}


@dataclass(frozen=True)
class RedmineIssue:
    """Created issue as returned by the Redmine API."""

    id: int
    subject: str
    project_id: str
    tracker_id: str
    status_id: str
    priority_id: str
    url: str
    author_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_api(cls, data: dict[str, Any], *, base_url: str) -> RedmineIssue:
        """Build the value object from a Redmine API response."""
        return cls(
            id=int(data["id"]),
            subject=str(data.get("subject", "")),
            project_id=str(data.get("project", {}).get("id", "")),
            tracker_id=str(data.get("tracker", {}).get("id", "")),
            status_id=str(data.get("status", {}).get("id", "")),
            priority_id=str(data.get("priority", {}).get("id", "")),
            author_id=str(data.get("author", {}).get("id", "")),
            url=f"{base_url.rstrip('/')}/issues/{int(data['id'])}",
            created_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class RedmineTicketResult:
    """Outcome of an error-ticketing attempt."""

    kind: RedmineErrorKind
    issue: RedmineIssue | None = None
    error: str = ""
    deduplicated: bool = False

    @property
    def ok(self) -> bool:
        return self.issue is not None and not self.error


class RedmineError(Exception):
    """Base class for Redmine integration failures."""


class RedmineConfigurationError(RedmineError):
    """Raised when the integration is not configured or misconfigured."""


class RedmineAPIError(RedmineError):
    """Raised for HTTP/API failures from the Redmine instance."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RedmineAuthenticationError(RedmineAPIError):
    """Raised on 401/403 responses."""


class RedmineUnavailableError(RedmineError):
    """Raised when Redmine is temporarily unavailable during self-healing.

    The orchestration layer treats this as a retryable signal so an
    already-created issue is only reopened, never duplicated.
    """


class RedmineDeduplicationError(RedmineError):
    """Raised when duplicate suppression cannot be performed safely."""


def redmine_config_from_env(
    env: dict[str, str] | None = None,
) -> RedmineConfig | None:
    """Build a :class:`RedmineConfig` from ``REDMINE_*`` environment variables.

    Returns ``None`` when the integration is not configured (no URL), so
    callers can fall back to ticketing-disabled behaviour. Extra keys are
    ignored; invalid numbers raise :class:`ValueError` for fast feedback.
    """
    env = dict(env or os.environ)
    url = (env.get("REDMINE_URL") or "").strip()
    api_key = (env.get("REDMINE_API_KEY") or "").strip()
    username = (env.get("REDMINE_USERNAME") or "").strip()
    password = (env.get("REDMINE_PASSWORD") or "").strip()
    if not url:
        return None

    def _float(key: str, default: float) -> float:
        raw = (env.get(key) or "").strip()
        return float(raw) if raw else default

    def _int(key: str, default: str) -> str:
        raw = (env.get(key) or "").strip()
        return str(int(raw)) if raw else default

    config = RedmineConfig(
        url=url,
        api_key=api_key,
        username=username,
        password=password,
        project_id=_int("REDMINE_PROJECT_ID", "1"),
        tracker_id=_int("REDMINE_ISSUE_TRACKER_ID", "1"),
        priority_id=_int("REDMINE_PRIORITY_ID", RedmineIssuePriority.NORMAL.value),
        status_id=_int("REDMINE_STATUS_ID", RedmineIssueStatus.NEW.value),
        timeout=_float("REDMINE_TIMEOUT", 15.0),
        retry_count=int(_int("REDMINE_RETRY_COUNT", "2")),
        retry_delay=_float("REDMINE_RETRY_DELAY", 1.0),
        verify_tls=(
            env.get("REDMINE_VERIFY_TLS", "1").strip().lower()
            not in {"0", "false", "no"}
        ),
    )
    config.validate()
    return config
