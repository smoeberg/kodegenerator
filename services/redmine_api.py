"""Redmine REST transport and issue operations.

Implements the read (search) and write (create, update) operations used
by the error-ticketing orchestration. Uses ``requests`` with bounded
retries on transient HTTP failures, mirroring
:mod:`services.github_pr_api`.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from services.redmine_contracts import (
    RedmineAPIError,
    RedmineAuthenticationError,
    RedmineConfig,
    RedmineIssue,
    RedmineIssueDraft,
    RedmineUnavailableError,
)


class RedmineAPIClient:
    """Thin, configurable REST client for a Redmine instance."""

    def __init__(self, config: RedmineConfig) -> None:
        config.validate()
        self.config = config

    # -- auth -----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.config.api_key:
            headers["X-Redmine-API-Key"] = self.config.api_key
        return headers

    def _auth(self) -> tuple[str, str] | None:
        if self.config.api_key:
            return None
        return (self.config.username, self.config.password)

    # -- transport ------------------------------------------------------

    def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.config.url.rstrip('/')}{endpoint}"
        last_error: Exception | None = None
        for attempt in range(self.config.retry_count):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=self._headers(),
                    auth=self._auth(),
                    json=data,
                    params=params,
                    timeout=self.config.timeout,
                    verify=self.config.verify_tls,
                )
            except requests.exceptions.Timeout as exc:
                last_error = exc
                if attempt < self.config.retry_count - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                raise RedmineUnavailableError(
                    f"Redmine request timed out after {self.config.timeout}s"
                ) from exc
            except requests.exceptions.RequestException as exc:
                last_error = exc
                if attempt < self.config.retry_count - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                raise RedmineUnavailableError(f"Redmine request failed: {exc}") from exc

            if response.status_code in (502, 503, 504):
                if attempt < self.config.retry_count - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                raise RedmineUnavailableError(
                    f"Redmine unavailable (HTTP {response.status_code})"
                )

            if response.status_code >= 400:
                message = self._error_message(response)
                if response.status_code in (401, 403):
                    raise RedmineAuthenticationError(
                        f"Redmine authentication failed (HTTP {response.status_code}): {message}",
                        response.status_code,
                    )
                raise RedmineAPIError(
                    f"Redmine API error (HTTP {response.status_code}): {message}",
                    response.status_code,
                )

            return response.json() if response.text else {}
        raise RedmineUnavailableError(
            f"Redmine request failed after {self.config.retry_count} attempts: {last_error}"
        )

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            body = response.json()
            errors = body.get("errors")
            if errors:
                return "; ".join(str(e) for e in errors)
            return str(body.get("message", response.text[:200]))
        except ValueError:
            return response.text[:200]

    # -- operations -----------------------------------------------------

    def create_issue(self, draft: RedmineIssueDraft) -> RedmineIssue:
        """Create a new issue and return the normalized value object."""
        response = self._request("POST", "/issues.json", data=draft.payload())
        return RedmineIssue.from_api(response["issue"], base_url=self.config.url)

    def update_issue(
        self,
        issue_id: int,
        *,
        subject: str | None = None,
        description: str | None = None,
        status_id: str | None = None,
        priority_id: str | None = None,
    ) -> RedmineIssue:
        """Update an existing issue (used for re-opening/logging and notes)."""
        issue: dict[str, Any] = {}
        if subject is not None:
            issue["subject"] = subject
        if description is not None:
            issue["description"] = description
        if status_id is not None:
            issue["status_id"] = status_id
        if priority_id is not None:
            issue["priority_id"] = priority_id
        response = self._request(
            "PUT", f"/issues/{issue_id}.json", data={"issue": issue}
        )
        if not response:
            return RedmineIssue(
                id=issue_id,
                subject=subject or "",
                project_id=str(self.config.project_id),
                tracker_id=str(self.config.tracker_id),
                status_id=status_id or self.config.status_id,
                priority_id=priority_id or self.config.priority_id,
                url=f"{self.config.url.rstrip('/')}/issues/{issue_id}",
            )
        return RedmineIssue.from_api(response["issue"], base_url=self.config.url)

    def search_issue(
        self,
        subject: str,
        *,
        limit: int = 5,
    ) -> list[RedmineIssue]:
        """Search for existing issues by subject (exact match preferred).

        Used by the deduplication guard so recurring verification
        failures reopen the same ticket instead of spamming duplicates.
        """
        try:
            response = self._request(
                "GET",
                "/issues.json",
                params={"subject": subject, "limit": limit},
            )
        except RedmineAPIError:
            return []
        issues = response.get("issues", [])
        return [
            RedmineIssue.from_api(item, base_url=self.config.url) for item in issues
        ]
