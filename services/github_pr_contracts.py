"""Immutable contracts and public errors for the GitHub PR integration.

Keeping transport-neutral values here prevents the API client, webhook parser,
and orchestration service from collapsing into one untestable module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PRStatus(str, Enum):
    PENDING = "pending"
    CREATED = "created"
    UPDATED = "updated"
    MERGED = "merged"
    CLOSED = "closed"
    FAILED = "failed"


class PRAction(str, Enum):
    OPENED = "opened"
    CLOSED = "closed"
    MERGED = "merged"
    REOPENED = "reopened"
    SYNCHRONIZE = "synchronize"
    READY_FOR_REVIEW = "ready_for_review"
    CONVERTED_TO_DRAFT = "converted_to_draft"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_REQUEST_REMOVED = "review_request_removed"


class WebhookEventType(str, Enum):
    PULL_REQUEST = "pull_request"
    PUSH = "push"
    ISSUE_COMMENT = "issue_comment"
    PULL_REQUEST_REVIEW_COMMENT = "pull_request_review_comment"
    PULL_REQUEST_REVIEW = "pull_request_review"
    STATUS = "status"
    CHECK_SUITE = "check_suite"
    CHECK_RUN = "check_run"


class AuthMethod(str, Enum):
    TOKEN = "token"
    APP = "app"


@dataclass(frozen=True)
class GitHubConfig:
    api_url: str = "https://api.github.com"
    user_agent: str = "kodegenerator-github-bot/1.0.0"
    timeout: int = 30
    retry_count: int = 3
    retry_delay: float = 1.0


@dataclass(frozen=True)
class TokenAuthConfig:
    token: str
    token_type: str = "bearer"


@dataclass(frozen=True)
class AppAuthConfig:
    app_id: str
    private_key: str
    installation_id: str | None = None


@dataclass(frozen=True)
class PRMetadata:
    title: str
    description: str
    branch: str
    base_branch: str = "main"
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)
    draft: bool = False


@dataclass(frozen=True)
class PatchInfo:
    patch_content: str
    patch_id: str
    author: str
    summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class CommitInfo:
    commit_hash: str
    message: str
    author_name: str
    author_email: str
    timestamp: datetime
    signed: bool = False
    signature: str | None = None


@dataclass(frozen=True)
class ChangelogEntry:
    version: str
    timestamp: datetime
    author: str
    changes: list[str] = field(default_factory=list)
    breaking_changes: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"## [{self.version}] - {self.timestamp.strftime('%Y-%m-%d')}", ""]
        for heading, entries in (
            ("Breaking Changes", self.breaking_changes),
            ("Features", self.features),
            ("Fixes", self.fixes),
            ("Changes", self.changes),
        ):
            if entries:
                lines.extend([f"### {heading}", *(f"- {entry}" for entry in entries), ""])
        lines.append("---")
        return "\n".join(lines)


@dataclass(frozen=True)
class PRResult:
    pr_number: int | None = None
    pr_url: str | None = None
    status: PRStatus = PRStatus.PENDING
    commit_hash: str | None = None
    changelog_entry: ChangelogEntry | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookPayload:
    event_type: WebhookEventType
    action: str | None = None
    repository: dict[str, Any] = field(default_factory=dict)
    pull_request: dict[str, Any] | None = None
    comment: dict[str, Any] | None = None
    issue: dict[str, Any] | None = None
    sender: dict[str, Any] = field(default_factory=dict)
    installation: dict[str, Any] | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WebhookResponse:
    status: str
    message: str
    actions: list[str] = field(default_factory=list)
    pr_number: int | None = None
    comment_id: int | None = None


class GitHubPRBotError(Exception):
    """Base exception for GitHub PR Bot errors."""


class GitHubAPIError(GitHubPRBotError):
    def __init__(
        self,
        message: str,
        status_code: int,
        response: dict[str, Any] | None = None,
    ):
        self.status_code = status_code
        self.response = response or {}
        super().__init__(f"{message} (status: {status_code})")


class AuthenticationError(GitHubPRBotError):
    """GitHub authentication failed."""


class WebhookVerificationError(GitHubPRBotError):
    """Webhook signature or delivery metadata was invalid."""


class RateLimitError(GitHubPRBotError):
    """GitHub API rate limit was exceeded."""
