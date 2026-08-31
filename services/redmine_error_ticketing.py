"""Error ticketing to Redmine for the Spec-to-Code / self-healing loops.

Maps DOR verification and generation failures onto Redmine issues so the
team sees recurring synthesis failures as trackable tickets — without
spamming duplicates: the same failure signature re-opens the existing
issue instead of creating a new one.

The adapter degrades gracefully: when Redmine is not configured (the
default in development) it no-ops and returns a non-ok
:class:`RedmineTicketResult` with ``error="not-configured"`` instead of
raising, so the generation loop is never blocked by ticketing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from services.redmine_api import RedmineAPIClient
from services.redmine_contracts import (
    RedmineAPIError,
    RedmineAuthenticationError,
    RedmineConfig,
    RedmineErrorKind,
    RedmineIssue,
    RedmineIssueDraft,
    RedmineIssuePriority,
    RedmineIssueStatus,
    RedmineTicketResult,
    RedmineUnavailableError,
)


def redmine_config_from_env(
    env: dict[str, str] | None = None,
) -> RedmineConfig | None:
    """Build a :class:`RedmineConfig` from DOR environment variables.

    Returns ``None`` (ticketing disabled) when ``REDMINE_URL`` is unset,
    so development and CI runs without Redmine stay green.
    """
    env = os.environ if env is None else env
    url = env.get("REDMINE_URL", "").strip()
    if not url:
        return None
    project_id = env.get("REDMINE_PROJECT_ID", "1").strip()
    tracker_id = env.get("REDMINE_TRACKER_ID", "1").strip()
    priority_id = env.get("REDMINE_PRIORITY_ID", "3").strip()  # 3 = High
    return RedmineConfig(
        url=url,
        api_key=env.get("REDMINE_API_KEY", "").strip(),
        username=env.get("REDMINE_USERNAME", "").strip(),
        password=env.get("REDMINE_PASSWORD", "").strip(),
        project_id=project_id or "1",
        tracker_id=tracker_id or "1",
        priority_id=priority_id or RedmineIssuePriority.HIGH.value,
        status_id=env.get("REDMINE_STATUS_ID", RedmineIssueStatus.NEW.value).strip(),
        timeout=float(env.get("REDMINE_TIMEOUT", "15")),
        verify_tls=env.get("REDMINE_VERIFY_TLS", "true").strip().lower() != "false",
    )


@dataclass(frozen=True)
class FailureSignature:
    """Stable identity for one recurring failure."""

    kind: RedmineErrorKind
    module: str
    error: str

    @classmethod
    def from_verification(
        cls,
        *,
        module: str,
        error: str,
        kind: RedmineErrorKind = RedmineErrorKind.VERIFICATION,
    ) -> FailureSignature:
        """Build a signature from a failed verification."""
        normalized = " ".join(error.strip().split())[:400].lower()
        return cls(kind=kind, module=module, error=normalized)

    @property
    def fingerprint(self) -> str:
        """Short stable hash used for deduplication/topic suffix."""
        payload = f"{self.kind.value}|{self.module}|{self.error}"
        return sha256(payload.encode("utf-8")).hexdigest()[:10]

    @property
    def subject(self) -> str:
        short = self.error[:110]
        return f"[DOR] {self.kind.value} failure: {self.module}: {short}"


@dataclass
class RedmineErrorTicker:
    """Defaults for the orchestration adapter."""

    use_deduplication: bool = True
    max_subject_length: int = 200
    max_description_length: int = 40_000
    _created: set[int] = field(default_factory=set, repr=False)


@dataclass(frozen=True)
class RedmineErrorTickerState:
    """Immutable snapshot of ticker settings (for logging/audit)."""

    configured: bool
    use_deduplication: bool = True


class RedmineErrorTickerService:
    """Send DOR verification failures to Redmine as trackable issues."""

    def __init__(
        self,
        client: RedmineAPIClient | None,
        *,
        use_deduplication: bool = True,
        max_subject_length: int = 200,
        max_description_length: int = 40_000,
    ) -> None:
        self.client = client
        self.use_deduplication = use_deduplication
        self.max_subject_length = max_subject_length
        self.max_description_length = max_description_length
        self._created: set[int] = set()

    # -- public API -----------------------------------------------------

    def report_verification_failure(
        self,
        *,
        module: str,
        error: str,
        context: dict[str, Any] | None = None,
        kind: RedmineErrorKind = RedmineErrorKind.VERIFICATION,
    ) -> RedmineTicketResult:
        """Report a failed verification (generation/self-healing) to Redmine."""
        signature = FailureSignature.from_verification(
            module=module, error=error, kind=kind
        )
        return self._send(signature, context or {})

    def report_self_healing_exhaustion(
        self,
        *,
        module: str,
        error: str,
        attempts: int,
        context: dict[str, Any] | None = None,
    ) -> RedmineTicketResult:
        """Report a self-healing loop that exhausted its attempts."""
        signature = FailureSignature.from_verification(
            module=module,
            error=error,
            kind=RedmineErrorKind.SELF_HEALING,
        )
        ctx = dict(context or {})
        ctx["self_healing_attempts"] = attempts
        return self._send(signature, ctx)

    # -- internals ------------------------------------------------------

    def _send(
        self, signature: FailureSignature, context: dict[str, Any]
    ) -> RedmineTicketResult:
        if self.client is None:
            return RedmineTicketResult(kind=signature.kind, error="not-configured")

        # Deduplication: re-open the existing issue instead of duplicating.
        if self.use_deduplication:
            existing = self._find_existing(signature)
            if existing is not None:
                try:
                    updated = self.client.update_issue(
                        existing.id,
                        status_id=RedmineIssueStatus.IN_PROGRESS.value,
                        description=self._render_description(signature, context),
                    )
                except RedmineAuthenticationError:
                    return RedmineTicketResult(
                        kind=signature.kind,
                        issue=existing,
                        error="authentication-failed",
                        deduplicated=True,
                    )
                except RedmineAPIError as exc:
                    return RedmineTicketResult(
                        kind=signature.kind,
                        issue=existing,
                        error=f"update-failed: {exc}",
                        deduplicated=True,
                    )
                self._created.add(updated.id)
                return RedmineTicketResult(
                    kind=signature.kind,
                    issue=updated,
                    deduplicated=True,
                )

        draft = RedmineIssueDraft(
            subject=self._truncate(signature.subject, self.max_subject_length),
            description=self._render_description(signature, context),
            project_id=self.client.config.project_id,
            tracker_id=self.client.config.tracker_id,
            priority_id=self.client.config.priority_id,
            status_id=self.client.config.status_id,
        )
        try:
            issue = self.client.create_issue(draft)
        except RedmineAuthenticationError as exc:
            return RedmineTicketResult(
                kind=signature.kind, error=f"authentication-failed: {exc}"
            )
        except RedmineAPIError as exc:
            return RedmineTicketResult(
                kind=signature.kind, error=f"create-failed: {exc}"
            )
        except RedmineUnavailableError as exc:
            return RedmineTicketResult(kind=signature.kind, error=f"unavailable: {exc}")
        self._created.add(issue.id)
        return RedmineTicketResult(kind=signature.kind, issue=issue)

    def _find_existing(self, signature: FailureSignature) -> RedmineIssue | None:
        """Find an open Redmine issue with the same subject."""
        assert self.client is not None
        for issue in self.client.search_issue(signature.subject, limit=10):
            if issue.subject == signature.subject:
                return issue
        return None

    def _render_description(
        self, signature: FailureSignature, context: dict[str, Any]
    ) -> str:
        lines = [
            f"**Kind:** `{signature.kind.value}`",
            f"**Module:** `{signature.module}`",
            f"**Fingerprint:** `{signature.fingerprint}`",
            f"**Reported:** {datetime.now(timezone.utc).isoformat()}",
            "",
            "**Error:**",
            "```",
            self._truncate(signature.error, self.max_description_length),
            "```",
        ]
        for key, value in context.items():
            lines.append("")
            lines.append(f"**{key}:**")
            lines.append("```")
            lines.append(self._truncate(str(value), self.max_description_length))
            lines.append("```")
        return "\n".join(lines)

    @staticmethod
    def _truncate(value: str, limit: int) -> str:
        value = value.strip()
        return value if len(value) <= limit else value[: limit - 1] + "…"
