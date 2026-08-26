"""Patch-to-PR orchestration and commit-signing workflow."""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

from services.github_pr_contracts import (
    ChangelogEntry,
    PatchInfo,
    PRMetadata,
    PRResult,
    PRStatus,
)

logger = logging.getLogger(__name__)


class GitHubPRWorkflowMixin:
    """Coordinate formatter and API capabilities without owning transport state."""

    def apply_patch_and_create_pr(
        self,
        patch: PatchInfo,
        pr_metadata: PRMetadata,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
    ) -> PRResult:
        warnings: list[str] = []
        try:
            changelog = self._generate_changelog(patch, wbs_summary, test_results)
            pr_result = self.create_pull_request(
                title=pr_metadata.title,
                body=self._format_pr_body(patch, wbs_summary, test_results, changelog),
                head=pr_metadata.branch,
                base=pr_metadata.base_branch,
                draft=pr_metadata.draft,
                labels=pr_metadata.labels,
                assignees=pr_metadata.assignees,
                reviewers=pr_metadata.reviewers,
            )
            if pr_result.status != PRStatus.CREATED:
                return PRResult(
                    status=PRStatus.FAILED,
                    errors=pr_result.errors,
                    warnings=warnings,
                )
            if pr_result.pr_number:
                self.add_pr_comment(
                    pr_result.pr_number,
                    self._generate_status_comment(patch, wbs_summary, test_results),
                )
            return PRResult(
                pr_number=pr_result.pr_number,
                pr_url=pr_result.pr_url,
                status=PRStatus.CREATED,
                changelog_entry=changelog,
                warnings=warnings,
                metadata={
                    **pr_result.metadata,
                    "wbs_summary": wbs_summary,
                    "test_results": test_results,
                },
            )
        except Exception as exc:
            logger.exception("Patch-to-PR workflow failed")
            return PRResult(
                status=PRStatus.FAILED,
                errors=[str(exc)],
                warnings=warnings,
            )

    def _generate_changelog(
        self,
        patch: PatchInfo,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
    ) -> ChangelogEntry:
        return self._formatter.generate_changelog(patch, wbs_summary, test_results)

    def _format_pr_body(
        self,
        patch: PatchInfo,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
        changelog: ChangelogEntry,
    ) -> str:
        return self._formatter.format_pr_body(
            patch, wbs_summary, test_results, changelog
        )

    def _format_test_results(self, test_results: dict[str, Any]) -> str:
        return self._formatter.format_test_results(test_results)

    def _format_wbs_summary(self, wbs_summary: dict[str, Any]) -> str:
        return self._formatter.format_wbs_summary(wbs_summary)

    def _generate_status_comment(
        self,
        patch: PatchInfo,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
    ) -> str:
        return self._formatter.generate_status_comment(patch, wbs_summary, test_results)

    def sign_commit(self, commit_sha: str, message: str) -> str | None:
        try:
            signature = self._sign_data(f"tree {commit_sha}\n{message}")
            return base64.b64encode(signature.encode()).decode()
        except Exception:
            logger.exception("Commit signing failed", extra={"commit_sha": commit_sha})
            return None

    def create_signed_commit(
        self,
        message: str,
        tree_sha: str,
        parent_sha: str,
        author: dict[str, str],
        sign: bool = True,
    ) -> tuple[dict[str, Any], str | None]:
        commit_data = self.create_commit(
            message=message,
            tree_sha=tree_sha,
            parent_sha=parent_sha,
            author=author,
        )
        commit_sha = commit_data.get("sha")
        if not commit_sha:
            return commit_data, None
        return (
            commit_data,
            self.sign_commit(commit_sha, message) if sign else None,
        )

    def validate_patch(self, patch: PatchInfo) -> tuple[bool, list[str]]:
        errors: list[str] = []
        if not patch.patch_content.strip():
            errors.append("Patch content is empty")
        if not patch.patch_id:
            errors.append("Patch ID is required")
        if not patch.author:
            errors.append("Author is required")
        return not errors, errors

    def get_pr_template(
        self,
        wbs_summary: dict[str, Any],
        test_results: dict[str, Any],
    ) -> str:
        return self._format_pr_body(
            PatchInfo(
                patch_id="template",
                patch_content="",
                author="template",
            ),
            wbs_summary,
            test_results,
            ChangelogEntry(
                version="template",
                timestamp=datetime.now(timezone.utc),
                author="template",
            ),
        )


__all__ = ["GitHubPRWorkflowMixin"]
