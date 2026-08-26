"""GitHub REST transport and repository operations for the PR bot."""

from __future__ import annotations

import time
from typing import Any

import requests

from services.github_pr_contracts import (
    AuthenticationError,
    GitHubAPIError,
    PRResult,
    PRStatus,
    RateLimitError,
)


class GitHubAPIClientMixin:
    """Cohesive GitHub API operations composed into :class:`GitHubPRBot`."""

    def _api_request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated request and normalize GitHub API failures."""
        url = f"{self.config.api_url}{endpoint}"
        headers = self._auth.get_headers()
        actual_timeout = timeout or self.config.timeout

        for attempt in range(self.config.retry_count):
            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=data,
                    params=params,
                    timeout=actual_timeout,
                )
                remaining = int(response.headers.get("x-ratelimit-remaining", 0))
                if remaining == 0:
                    reset_time = int(response.headers.get("x-ratelimit-reset", 0))
                    wait_time = max(reset_time - time.time(), 0) + 10
                    if attempt < self.config.retry_count - 1:
                        time.sleep(wait_time)
                        continue
                    raise RateLimitError(
                        f"Rate limit exceeded. Reset in {wait_time} seconds."
                    )

                if response.status_code >= 400:
                    error_data = response.json() if response.text else {}
                    message = error_data.get("message", "Unknown error")
                    if response.status_code == 401:
                        raise AuthenticationError(f"Authentication failed: {message}")
                    if response.status_code == 403:
                        if "rate limit" in message.lower():
                            raise RateLimitError(f"Rate limit exceeded: {message}")
                        raise GitHubAPIError(
                            f"Forbidden: {message}", response.status_code, error_data
                        )
                    if response.status_code == 404:
                        raise GitHubAPIError(
                            f"Not found: {error_data.get('message', endpoint)}",
                            response.status_code,
                            error_data,
                        )
                    raise GitHubAPIError(
                        f"API error: {message}", response.status_code, error_data
                    )

                return response.json() if response.text else {}
            except requests.exceptions.Timeout:
                if attempt < self.config.retry_count - 1:
                    time.sleep(self.config.retry_delay * (attempt + 1))
                    continue
                raise GitHubAPIError(
                    f"Request timeout after {actual_timeout} seconds", 408
                )
            except requests.exceptions.RequestException as exc:
                raise GitHubAPIError(f"Request failed: {exc}", 0) from exc

        raise GitHubAPIError("Max retries exceeded", 0)

    def get_repo_info(self) -> dict[str, Any]:
        return self._api_request("GET", f"/repos/{self.repo_full_name}")

    def get_branch(self, branch: str) -> dict[str, Any]:
        return self._api_request(
            "GET", f"/repos/{self.repo_full_name}/branches/{branch}"
        )

    def get_default_branch(self) -> str:
        return self.get_repo_info().get("default_branch", "main")

    def create_branch(self, branch_name: str, sha: str) -> dict[str, Any]:
        return self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/git/refs",
            {"ref": f"refs/heads/{branch_name}", "sha": sha},
        )

    def create_commit(
        self,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: dict[str, str],
        committer: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/git/commits",
            {
                "message": message,
                "tree": tree_sha,
                "parents": [parent_sha],
                "author": author,
                "committer": committer or author,
            },
        )

    def create_blob(self, content: str, encoding: str = "utf-8") -> dict[str, Any]:
        return self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/git/blobs",
            {"content": content, "encoding": encoding},
        )

    def create_tree(
        self,
        tree: list[dict[str, Any]],
        base_tree_sha: str | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {"tree": tree}
        if base_tree_sha:
            data["base_tree"] = base_tree_sha
        return self._api_request(
            "POST", f"/repos/{self.repo_full_name}/git/trees", data
        )

    def get_tree(self, tree_sha: str, recursive: bool = False) -> dict[str, Any]:
        return self._api_request(
            "GET",
            f"/repos/{self.repo_full_name}/git/trees/{tree_sha}",
            params={"recursive": str(recursive).lower()},
        )

    def get_commit(self, commit_sha: str) -> dict[str, Any]:
        return self._api_request(
            "GET", f"/repos/{self.repo_full_name}/git/commits/{commit_sha}"
        )

    def get_reference(self, ref: str) -> dict[str, Any]:
        return self._api_request("GET", f"/repos/{self.repo_full_name}/git/{ref}")

    def update_reference(
        self,
        ref: str,
        sha: str,
        force: bool = False,
    ) -> dict[str, Any]:
        return self._api_request(
            "PATCH",
            f"/repos/{self.repo_full_name}/git/refs/{ref}",
            {"sha": sha, "force": force},
        )

    def create_pull_request(
        self,
        title: str,
        body: str,
        head: str,
        base: str,
        draft: bool = False,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        reviewers: list[str] | None = None,
    ) -> PRResult:
        data: dict[str, Any] = {
            "title": title,
            "body": body,
            "head": head,
            "base": base,
            "draft": draft,
        }
        if labels:
            data["labels"] = labels
        if assignees:
            data["assignees"] = assignees
        try:
            pr_data = self._api_request(
                "POST", f"/repos/{self.repo_full_name}/pulls", data
            )
            pr_number = pr_data.get("number")
            if reviewers and pr_number:
                self._add_reviewers(pr_number, reviewers)
            return PRResult(
                pr_number=pr_number,
                pr_url=pr_data.get("html_url"),
                status=PRStatus.CREATED,
                metadata=pr_data,
            )
        except GitHubAPIError as exc:
            return PRResult(
                status=PRStatus.FAILED,
                errors=[f"Failed to create PR: {exc}"],
            )

    def _add_reviewers(self, pr_number: int, reviewers: list[str]) -> None:
        self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/pulls/{pr_number}/requested_reviewers",
            {"reviewers": reviewers},
        )

    def get_pull_request(self, pr_number: int) -> dict[str, Any]:
        return self._api_request(
            "GET", f"/repos/{self.repo_full_name}/pulls/{pr_number}"
        )

    def update_pull_request(
        self,
        pr_number: int,
        title: str | None = None,
        body: str | None = None,
        base: str | None = None,
        labels: list[str] | None = None,
        state: str | None = None,
    ) -> PRResult:
        data = {
            key: value
            for key, value in (
                ("title", title),
                ("body", body),
                ("base", base),
                ("labels", labels),
                ("state", state),
            )
            if value is not None
        }
        if not data:
            return PRResult(status=PRStatus.PENDING, errors=["No fields to update"])
        try:
            pr_data = self._api_request(
                "PATCH", f"/repos/{self.repo_full_name}/pulls/{pr_number}", data
            )
            return PRResult(
                pr_number=pr_number,
                pr_url=pr_data.get("html_url"),
                status=PRStatus.UPDATED,
                metadata=pr_data,
            )
        except GitHubAPIError as exc:
            return PRResult(
                status=PRStatus.FAILED,
                errors=[f"Failed to update PR: {exc}"],
            )

    def add_pr_comment(self, pr_number: int, body: str) -> dict[str, Any]:
        return self._api_request(
            "POST",
            f"/repos/{self.repo_full_name}/issues/{pr_number}/comments",
            {"body": body},
        )

    def merge_pull_request(
        self,
        pr_number: int,
        commit_title: str | None = None,
        merge_method: str = "squash",
    ) -> PRResult:
        data: dict[str, Any] = {"merge_method": merge_method}
        if commit_title:
            data["commit_title"] = commit_title
        try:
            result = self._api_request(
                "PUT",
                f"/repos/{self.repo_full_name}/pulls/{pr_number}/merge",
                data,
            )
            if result.get("merged", False):
                return PRResult(
                    pr_number=pr_number,
                    status=PRStatus.MERGED,
                    commit_hash=result.get("sha"),
                    metadata=result,
                )
            return PRResult(
                pr_number=pr_number,
                status=PRStatus.FAILED,
                errors=[result.get("message", "Merge failed")],
                metadata=result,
            )
        except GitHubAPIError as exc:
            return PRResult(
                status=PRStatus.FAILED,
                errors=[f"Failed to merge PR: {exc}"],
            )


__all__ = ["GitHubAPIClientMixin"]
