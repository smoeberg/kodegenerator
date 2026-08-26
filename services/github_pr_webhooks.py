"""Transport-neutral GitHub webhook verification, parsing, and routing."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
from typing import Any, Protocol

from services.github_pr_contracts import (
    PRAction,
    PRStatus,
    WebhookEventType,
    WebhookPayload,
    WebhookResponse,
    WebhookVerificationError,
)

GITHUB_WEBHOOK_SIGNATURE_HEADER = "x-hub-signature-256"
GITHUB_WEBHOOK_EVENT_HEADER = "x-github-event"
GITHUB_WEBHOOK_DELIVERY_HEADER = "x-github-delivery"

logger = logging.getLogger(__name__)


class WebhookRequest(Protocol):
    """Minimal request contract required by the webhook application service."""

    headers: Any

    async def body(self) -> bytes: ...


class WebhookVerifier:
    """Verify GitHub's HMAC-SHA256 webhook signature."""

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode() if isinstance(secret, str) else secret

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        if not signature or not signature.startswith("sha256="):
            return False
        expected_hash = hmac.new(self._secret, payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected_hash, signature[7:])


class WebhookParser:
    """Parse raw GitHub webhook input into an immutable contract."""

    @staticmethod
    def parse_payload(
        body: bytes,
        event_type: str,
        action: str | None = None,
    ) -> WebhookPayload:
        try:
            payload = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise WebhookVerificationError(f"Invalid JSON payload: {exc}") from exc
        return WebhookPayload(
            event_type=WebhookEventType(event_type),
            action=action or payload.get("action"),
            repository=payload.get("repository", {}),
            pull_request=payload.get("pull_request"),
            comment=payload.get("comment"),
            issue=payload.get("issue"),
            sender=payload.get("sender", {}),
            installation=payload.get("installation"),
            raw_payload=payload,
        )


class GitHubPRWebhookMixin:
    """Route webhook contracts and command messages through bot operations."""

    async def process_webhook(self, request: WebhookRequest) -> WebhookResponse:
        body = await request.body()
        signature = request.headers.get(GITHUB_WEBHOOK_SIGNATURE_HEADER)
        event_type = request.headers.get(GITHUB_WEBHOOK_EVENT_HEADER)
        delivery_id = request.headers.get(GITHUB_WEBHOOK_DELIVERY_HEADER)

        if self._webhook_verifier and (
            not signature
            or not self._webhook_verifier.verify_signature(body, signature)
        ):
            raise WebhookVerificationError(
                f"Invalid webhook signature for delivery {delivery_id}"
            )
        try:
            payload = WebhookParser.parse_payload(body, event_type or "")
        except WebhookVerificationError as exc:
            return WebhookResponse(status="error", message=f"Invalid payload: {exc}")
        return self._route_webhook(payload)

    def _route_webhook(self, payload: WebhookPayload) -> WebhookResponse:
        event_type = payload.event_type
        try:
            handlers = {
                WebhookEventType.PULL_REQUEST: self._handle_pr_event,
                WebhookEventType.PUSH: self._handle_push_event,
                WebhookEventType.ISSUE_COMMENT: self._handle_issue_comment,
                WebhookEventType.PULL_REQUEST_REVIEW_COMMENT: (self._handle_pr_comment),
                WebhookEventType.PULL_REQUEST_REVIEW: self._handle_pr_review,
                WebhookEventType.STATUS: self._handle_status_event,
                WebhookEventType.CHECK_SUITE: self._handle_check_suite_event,
                WebhookEventType.CHECK_RUN: self._handle_check_run_event,
            }
            handler = handlers.get(event_type)
            if handler is None:
                return WebhookResponse(
                    status="ignored",
                    message=f"Unhandled event type: {event_type}",
                )
            return handler(payload)
        # This application boundary converts arbitrary handler failures into the
        # stable WebhookResponse contract after recording the full exception.
        except Exception as exc:
            logger.exception(
                "GitHub webhook handler failed",
                extra={"event_type": event_type.value},
            )
            return WebhookResponse(
                status="error",
                message=f"Error processing {event_type}: {exc}",
            )

    def _handle_pr_event(self, payload: WebhookPayload) -> WebhookResponse:
        pr = payload.pull_request
        action = payload.action
        if not pr or not action:
            return WebhookResponse(
                status="ignored", message="No pull request or action in payload"
            )

        pr_number = pr.get("number")
        handlers = {
            PRAction.OPENED.value: self._handle_pr_opened,
            PRAction.CLOSED.value: self._handle_pr_closed,
            PRAction.MERGED.value: self._handle_pr_merged,
            PRAction.SYNCHRONIZE.value: self._handle_pr_synchronized,
            PRAction.READY_FOR_REVIEW.value: self._handle_pr_ready_for_review,
        }
        handler = handlers.get(action)
        if handler is None:
            return WebhookResponse(
                status="ignored", message=f"Unhandled PR action: {action}"
            )
        return handler(pr_number, pr)

    def _handle_pr_opened(self, pr_number: int, pr: dict[str, Any]) -> WebhookResponse:
        commands = self._extract_commands(
            pr.get("body", "") + " " + pr.get("title", "")
        )
        if not commands:
            return WebhookResponse(
                status="ignored", message="No /kodegen commands found"
            )
        actions = [
            action
            for command in commands
            if (action := self._process_command(command, pr_number, pr))
        ]
        return WebhookResponse(
            status="processed",
            message=f"Processed {len(actions)} commands",
            actions=actions,
            pr_number=pr_number,
        )

    def _handle_pr_closed(self, pr_number: int, pr: dict[str, Any]) -> WebhookResponse:
        del pr
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} closed",
            pr_number=pr_number,
        )

    def _handle_pr_merged(self, pr_number: int, pr: dict[str, Any]) -> WebhookResponse:
        del pr
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} merged",
            pr_number=pr_number,
        )

    def _handle_pr_synchronized(
        self, pr_number: int, pr: dict[str, Any]
    ) -> WebhookResponse:
        del pr
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} synchronized",
            pr_number=pr_number,
        )

    def _handle_pr_ready_for_review(
        self, pr_number: int, pr: dict[str, Any]
    ) -> WebhookResponse:
        del pr
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} ready for review",
            pr_number=pr_number,
        )

    def _handle_push_event(self, payload: WebhookPayload) -> WebhookResponse:
        ref = payload.raw_payload.get("ref", "")
        commits = payload.raw_payload.get("commits", [])
        return WebhookResponse(
            status="acknowledged",
            message=f"Push to {ref} with {len(commits)} commits",
        )

    def _handle_issue_comment(self, payload: WebhookPayload) -> WebhookResponse:
        comment = payload.comment
        issue = payload.issue
        if not comment or not issue:
            return WebhookResponse(
                status="ignored", message="No comment or issue in payload"
            )
        commands = self._extract_commands(comment.get("body", ""))
        if not commands:
            return WebhookResponse(
                status="ignored", message="No /kodegen commands found"
            )
        issue_number = issue.get("number")
        actions = [
            action
            for command in commands
            if (action := self._process_issue_command(command, issue_number, comment))
        ]
        return WebhookResponse(
            status="processed",
            message=f"Processed {len(actions)} commands",
            actions=actions,
            comment_id=comment.get("id"),
        )

    def _handle_pr_comment(self, payload: WebhookPayload) -> WebhookResponse:
        comment = payload.comment
        pr = payload.pull_request
        if not comment or not pr:
            return WebhookResponse(
                status="ignored", message="No comment or PR in payload"
            )
        commands = self._extract_commands(comment.get("body", ""))
        if not commands:
            return WebhookResponse(
                status="ignored", message="No /kodegen commands found"
            )
        pr_number = pr.get("number")
        actions = [
            action
            for command in commands
            if (action := self._process_pr_comment_command(command, pr_number, comment))
        ]
        return WebhookResponse(
            status="processed",
            message=f"Processed {len(actions)} commands",
            actions=actions,
            pr_number=pr_number,
            comment_id=comment.get("id"),
        )

    def _handle_pr_review(self, payload: WebhookPayload) -> WebhookResponse:
        review = payload.raw_payload.get("review")
        pr = payload.pull_request
        if not review or not pr:
            return WebhookResponse(
                status="ignored", message="No review or PR in payload"
            )
        pr_number = pr.get("number")
        return WebhookResponse(
            status="acknowledged",
            message=f"PR #{pr_number} review: {review.get('state', '')}",
            pr_number=pr_number,
        )

    def _handle_status_event(self, payload: WebhookPayload) -> WebhookResponse:
        state = payload.raw_payload.get("state", "")
        description = payload.raw_payload.get("description", "")
        return WebhookResponse(
            status="acknowledged", message=f"Status: {state} - {description}"
        )

    def _handle_check_suite_event(self, payload: WebhookPayload) -> WebhookResponse:
        check_suite = payload.raw_payload.get("check_suite")
        if not check_suite:
            return WebhookResponse(
                status="ignored", message="No check suite in payload"
            )
        return WebhookResponse(
            status="acknowledged",
            message=(
                f"Check suite {payload.action}: {check_suite.get('conclusion', '')}"
            ),
        )

    def _handle_check_run_event(self, payload: WebhookPayload) -> WebhookResponse:
        check_run = payload.raw_payload.get("check_run")
        if not check_run:
            return WebhookResponse(status="ignored", message="No check run in payload")
        return WebhookResponse(
            status="acknowledged",
            message=(f"Check run {payload.action}: {check_run.get('conclusion', '')}"),
        )

    def _extract_commands(self, text: str) -> list[str]:
        commands: list[str] = []
        parts = re.split(r"(/kodegen\s+)", text, flags=re.IGNORECASE)
        index = 0
        while index < len(parts):
            if parts[index].lower().startswith("/kodegen"):
                command_parts = [parts[index]]
                next_index = index + 1
                while next_index < len(parts) and not parts[
                    next_index
                ].lower().startswith("/kodegen"):
                    command_parts.append(parts[next_index])
                    next_index += 1
                command = "".join(command_parts).strip()
                if command:
                    commands.append(command)
                index = next_index
            else:
                index += 1
        return commands

    def _process_command(
        self,
        command: str,
        pr_number: int,
        pr: dict[str, Any],
    ) -> str | None:
        del pr
        parts = command.split()
        if len(parts) < 2:
            return None
        command_name = parts[1].lower()
        args = parts[2:] if len(parts) > 2 else []
        handlers = {
            "fix": self._process_fix_command,
            "test": self._process_test_command,
            "rebase": self._process_rebase_command,
            "merge": self._process_merge_command,
            "status": self._process_status_command,
        }
        handler = handlers.get(command_name)
        return handler(pr_number, args) if handler else None

    def _process_issue_command(
        self,
        command: str,
        issue_number: int,
        comment: dict[str, Any],
    ) -> str | None:
        del issue_number, comment
        parts = command.split()
        if len(parts) < 2:
            return None
        return "Displaying help" if parts[1].lower() == "help" else None

    def _process_pr_comment_command(
        self,
        command: str,
        pr_number: int,
        comment: dict[str, Any],
    ) -> str | None:
        del comment
        return self._process_command(command, pr_number, {})

    def _process_fix_command(self, pr_number: int, args: list[str]) -> str:
        del args
        return f"Triggering fix workflow for PR #{pr_number}"

    def _process_test_command(self, pr_number: int, args: list[str]) -> str:
        del args
        return f"Re-running tests for PR #{pr_number}"

    def _process_rebase_command(self, pr_number: int, args: list[str]) -> str:
        del args
        return f"Rebasing PR #{pr_number}"

    def _process_merge_command(self, pr_number: int, args: list[str]) -> str:
        del args
        result = self.merge_pull_request(pr_number)
        if result.status == PRStatus.MERGED:
            return f"Merged PR #{pr_number}"
        return f"Failed to merge PR #{pr_number}: {', '.join(result.errors)}"

    def _process_status_command(self, pr_number: int, args: list[str]) -> str:
        del args
        status = self.get_pull_request(pr_number).get("state", "unknown")
        return f"PR #{pr_number} status: {status}"


__all__ = [
    "GITHUB_WEBHOOK_DELIVERY_HEADER",
    "GITHUB_WEBHOOK_EVENT_HEADER",
    "GITHUB_WEBHOOK_SIGNATURE_HEADER",
    "GitHubPRWebhookMixin",
    "WebhookParser",
    "WebhookRequest",
    "WebhookVerifier",
]
