"""Git Worktree & Pull Request Automation Engine.

Publishes verified patches to GitHub using ephemeral isolated git worktrees,
commit signing, and automated PR generation with fail-closed safety gates.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from phase4.authority.grants import VerifiedAuthorityGrant
from services.github_pr_api import GitHubAPIClientMixin
from services.github_pr_auth import GitHubAuthenticator
from services.github_pr_contracts import (
    GitHubConfig,
    PatchInfo,
    PRMetadata,
    PRResult,
    PRStatus,
)
from services.github_pr_formatting import GitHubPRFormatter
from services.github_pr_workflow import GitHubPRWorkflowMixin

logger = logging.getLogger(__name__)


class WorktreeExecutionError(Exception):
    """Raised when an operation inside a git worktree fails."""


class WorktreeSecurityError(Exception):
    """Raised when safety gates or authority verifications fail."""


@dataclass(frozen=True)
class WorktreeSession:
    """Represents an active isolated git worktree session."""

    session_id: str
    worktree_path: Path
    branch_name: str
    base_branch: str
    repo_root: Path
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class GitWorktreeManager:
    """Manages ephemeral, isolated Git worktrees for safe patch application."""

    def __init__(self, repo_root: Path | str) -> None:
        self.repo_root = Path(repo_root).resolve()
        if not (self.repo_root / ".git").exists():
            raise WorktreeExecutionError(
                f"Not a valid git repository: {self.repo_root}"
            )

    def create_worktree(
        self, branch_name: str, base_branch: str = "main"
    ) -> WorktreeSession:
        """Create an ephemeral worktree on a branch derived from ``base_branch``."""
        session_id = str(uuid4())[:8]
        temp_dir = Path(tempfile.mkdtemp(prefix=f"worktree_{session_id}_"))

        # Fetch latest or check if base branch exists
        try:
            # git worktree add -b <branch_name> <path> <base_branch>
            cmd = [
                "git",
                "worktree",
                "add",
                "-b",
                branch_name,
                str(temp_dir),
                base_branch,
            ]
            self._run_git(cmd, cwd=self.repo_root)
        except Exception as exc:
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise WorktreeExecutionError(
                f"Failed to create git worktree for branch {branch_name}: {exc}"
            ) from exc

        return WorktreeSession(
            session_id=session_id,
            worktree_path=temp_dir,
            branch_name=branch_name,
            base_branch=base_branch,
            repo_root=self.repo_root,
        )

    def cleanup_worktree(self, session: WorktreeSession, force: bool = True) -> None:
        """Remove worktree and prune metadata."""
        try:
            cmd = ["git", "worktree", "remove"]
            if force:
                cmd.append("--force")
            cmd.append(str(session.worktree_path))
            self._run_git(cmd, cwd=self.repo_root)
        except Exception as exc:
            logger.warning(
                "Error executing git worktree remove: %s. "
                "Falling back to manual cleanup.",
                exc,
            )
            if session.worktree_path.exists():
                shutil.rmtree(session.worktree_path, ignore_errors=True)
            try:
                self._run_git(["git", "worktree", "prune"], cwd=self.repo_root)
            except Exception:
                pass

    def apply_patch(self, session: WorktreeSession, patch_content: str) -> None:
        """Apply a unified diff patch inside the isolated worktree."""
        if not patch_content.strip():
            raise WorktreeExecutionError("Cannot apply empty patch")

        patch_file = session.worktree_path / ".applied_patch.diff"
        try:
            patch_file.write_text(patch_content, encoding="utf-8")
            # Apply via git apply with whitespace fix
            self._run_git(
                ["git", "apply", "--whitespace=nowarn", str(patch_file)],
                cwd=session.worktree_path,
            )
        except Exception as exc:
            raise WorktreeExecutionError(
                f"Patch application failed in worktree: {exc}"
            ) from exc
        finally:
            if patch_file.exists():
                patch_file.unlink(missing_ok=True)

    def stage_and_commit(
        self,
        session: WorktreeSession,
        message: str,
        author_name: str = "AI Code Generator",
        author_email: str = "ai-generator@rool.local",
    ) -> str:
        """Stage all changes in worktree and commit with author metadata."""
        self._run_git(["git", "add", "-A"], cwd=session.worktree_path)

        # Check if there are changes to commit
        status_out = self._run_git(
            ["git", "status", "--porcelain"], cwd=session.worktree_path
        )
        if not status_out.strip():
            # No changes to commit
            return self._run_git(
                ["git", "rev-parse", "HEAD"], cwd=session.worktree_path
            ).strip()

        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_COMMITTER_NAME"] = author_name
        env["GIT_COMMITTER_EMAIL"] = author_email

        cmd = ["git", "commit", "-m", message]
        self._run_git(cmd, cwd=session.worktree_path, env=env)
        commit_sha = self._run_git(
            ["git", "rev-parse", "HEAD"], cwd=session.worktree_path
        ).strip()
        return commit_sha

    def push_branch(
        self, session: WorktreeSession, remote: str = "origin", force: bool = False
    ) -> None:
        """Push branch from worktree to remote."""
        cmd = ["git", "push", "-u", remote, session.branch_name]
        if force:
            cmd.insert(2, "--force")
        self._run_git(cmd, cwd=session.worktree_path)

    def _run_git(
        self, cmd: List[str], cwd: Path, env: Optional[Dict[str, str]] = None
    ) -> str:
        """Run a git subcommand and return stdout."""
        res = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise WorktreeExecutionError(
                f"Git command failed: {' '.join(cmd)}\n"
                f"Stderr: {res.stderr}\nStdout: {res.stdout}"
            )
        return res.stdout


class GitPRPublisher(GitHubAPIClientMixin, GitHubPRWorkflowMixin):
    """Publish a verified patch through an isolated Git worktree and GitHub PR.

    The API token authenticates GitHub REST calls only. Git push credentials
    must be configured independently on the repository remote or credential
    helper. The publisher never merges the pull request or bypasses protected
    branch rules.
    """

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        token: str,
        repo_root: Optional[Path | str] = None,
        config: Optional[GitHubConfig] = None,
    ) -> None:
        """Configure a repository-scoped publisher.

        Args:
            owner: GitHub repository owner.
            repo: GitHub repository name.
            token: Secret token with contents and pull-request write access.
                The value is retained only by the authentication boundary and
                must not be logged or included in task payloads.
            repo_root: Local Git checkout used to create ephemeral worktrees.
            config: Optional API URL, retry, timeout, and user-agent policy.
        """
        self.owner = owner
        self.repo = repo
        self.repo_full_name = f"{owner}/{repo}"
        self.config = config or GitHubConfig()
        self._auth = GitHubAuthenticator(token=token)
        self._formatter = GitHubPRFormatter()
        self.worktree_manager = GitWorktreeManager(repo_root or Path.cwd())

    def publish_patch_as_pr(
        self,
        patch: PatchInfo,
        pr_metadata: PRMetadata,
        wbs_summary: Optional[Dict[str, Any]] = None,
        test_results: Optional[Dict[str, Any]] = None,
        authority_grant: Optional[VerifiedAuthorityGrant] = None,
        push_remote: bool = True,
    ) -> PRResult:
        """Execute full isolated worktree lifecycle and create GitHub Pull Request.

        The lifecycle validates authority and patch content, creates a unique
        worktree/branch, applies and commits the diff, optionally pushes it,
        creates the PR, posts a status comment, and always cleans up the
        worktree. An unverified or expired supplied grant fails closed.

        ``push_remote=False`` is intended for tests. Production publication
        normally requires ``True`` so the GitHub API can resolve the head ref.
        """
        # 1. Security & Authority Check. This boundary must fail closed even
        # when callers bypass ReleaseExecutor and invoke the publisher directly.
        if authority_grant is None:
            raise WorktreeSecurityError("VerifiedAuthorityGrant is required")
        if not authority_grant.verified:
            raise WorktreeSecurityError(
                "Authority grant failed cryptographic verification"
            )
        _validate_release_grant(
            authority_grant,
            repository=f"repository:{self.repo_full_name}",
            patch_id=patch.patch_id,
            base_branch=pr_metadata.base_branch,
        )
        if not _tests_passed(test_results):
            raise WorktreeSecurityError(
                "attested successful test evidence is required for publication"
            )

        is_valid, errors = self.validate_patch(patch)
        if not is_valid:
            return PRResult(
                status=PRStatus.FAILED,
                errors=errors,
            )

        wbs_data = wbs_summary or {"task": patch.patch_id, "summary": patch.summary}
        tests_data = dict(test_results)

        session: Optional[WorktreeSession] = None
        try:
            # 2. Spin up isolated worktree
            session = self.worktree_manager.create_worktree(
                branch_name=pr_metadata.branch,
                base_branch=pr_metadata.base_branch,
            )

            # 3. Apply patch inside worktree
            self.worktree_manager.apply_patch(session, patch.patch_content)

            # 4. Commit changes with attribution
            commit_msg = (
                f"{pr_metadata.title}\n\n"
                f"Task: {patch.patch_id}\nAuthor: {patch.author}\n\n"
                f"{patch.summary}"
            )
            commit_sha = self.worktree_manager.stage_and_commit(
                session=session,
                message=commit_msg,
                author_name=patch.author,
            )

            # 5. Push branch if enabled
            if push_remote:
                self.worktree_manager.push_branch(session)

            # 6. Generate PR via GitHub API
            changelog = self._generate_changelog(patch, wbs_data, tests_data)
            pr_body = self._format_pr_body(patch, wbs_data, tests_data, changelog)

            pr_result = self.create_pull_request(
                title=pr_metadata.title,
                body=pr_body,
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
                    commit_hash=commit_sha,
                    errors=pr_result.errors,
                    warnings=pr_result.warnings,
                )

            # Optional status comment
            if pr_result.pr_number:
                self.add_pr_comment(
                    pr_result.pr_number,
                    self._generate_status_comment(patch, wbs_data, tests_data),
                )

            return PRResult(
                pr_number=pr_result.pr_number,
                pr_url=pr_result.pr_url,
                status=PRStatus.CREATED,
                commit_hash=commit_sha,
                changelog_entry=changelog,
                metadata={
                    "branch": pr_metadata.branch,
                    "base_branch": pr_metadata.base_branch,
                    "commit_sha": commit_sha,
                    "wbs_summary": wbs_data,
                    "test_results": tests_data,
                },
            )

        except Exception as exc:
            logger.exception("Failed to publish PR via Git worktree")
            return PRResult(
                status=PRStatus.FAILED,
                errors=[str(exc)],
            )
        finally:
            if session is not None:
                self.worktree_manager.cleanup_worktree(session)


def _tests_passed(test_results: Optional[Dict[str, Any]]) -> bool:
    """Accept only explicit, non-empty successful test evidence."""
    if not isinstance(test_results, dict) or not test_results:
        return False
    summary = test_results.get("summary")
    evidence = summary if isinstance(summary, dict) else test_results
    status = str(evidence.get("status", test_results.get("status", ""))).lower()
    failed = evidence.get("failed", evidence.get("failures"))
    total = evidence.get("total", evidence.get("tests_run"))
    passed = evidence.get("passed")
    if status not in {"pass", "passed", "success", "succeeded"}:
        return False
    if failed not in (0, [], None):
        return False
    if total is not None and (not isinstance(total, int) or total < 1):
        return False
    if passed is not None and (not isinstance(passed, int) or passed < 1):
        return False
    return total is not None or passed is not None


def _validate_release_grant(
    grant: VerifiedAuthorityGrant,
    *,
    repository: str,
    patch_id: str,
    base_branch: str,
) -> None:
    """Require a grant scoped to this repository and exact release input."""
    parameters = dict(grant.parameters)
    if grant.action != "release.publish" or grant.resource != repository:
        raise WorktreeSecurityError("authority grant is not scoped to this repository")
    if parameters.get("patch_id") != patch_id:
        raise WorktreeSecurityError("authority grant is not bound to this patch")
    if parameters.get("base_branch") != base_branch:
        raise WorktreeSecurityError("authority grant is not bound to the base branch")


__all__ = [
    "WorktreeSession",
    "GitWorktreeManager",
    "GitPRPublisher",
    "WorktreeExecutionError",
    "WorktreeSecurityError",
]
