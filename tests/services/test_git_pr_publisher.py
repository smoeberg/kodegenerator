"""Unit and integration tests for GitPRPublisher and GitWorktreeManager."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phase4.authority.grants import VerifiedAuthorityGrant
from services.git_pr_publisher import (
    GitPRPublisher,
    GitWorktreeManager,
    WorktreeExecutionError,
    WorktreeSecurityError,
)
from services.github_pr_contracts import (
    PatchInfo,
    PRMetadata,
    PRResult,
    PRStatus,
)


@pytest.fixture
def temp_git_repo(tmp_path: Path):
    """Create a temporary initialized git repository with an initial commit."""
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_dir, check=True)

    dummy_file = repo_dir / "README.md"
    dummy_file.write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_dir, check=True, capture_output=True)

    return repo_dir


def test_worktree_lifecycle_and_patch_application(temp_git_repo: Path):
    """Test creating a worktree, applying a unified diff patch, committing, and cleaning up."""
    manager = GitWorktreeManager(temp_git_repo)
    branch = "feature/test-patch-1"

    session = manager.create_worktree(branch_name=branch, base_branch="main")
    assert session.worktree_path.exists()
    assert (session.worktree_path / ".git").exists()

    # Valid unified diff patch
    diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Test Repo\n"
        "+Added by patch\n"
    )

    manager.apply_patch(session, diff)
    readme_content = (session.worktree_path / "README.md").read_text(encoding="utf-8")
    assert "Added by patch" in readme_content

    commit_sha = manager.stage_and_commit(
        session=session,
        message="Apply test patch",
        author_name="Bot Author",
    )
    assert commit_sha is not None
    assert len(commit_sha) == 40

    # Cleanup worktree
    manager.cleanup_worktree(session)
    assert not session.worktree_path.exists()


def test_git_pr_publisher_end_to_end(temp_git_repo: Path):
    """Test full publisher execution creating branch, applying patch, and mocking GitHub PR API."""
    publisher = GitPRPublisher(
        owner="test-org",
        repo="test-repo",
        token="ghp_testtoken123",
        repo_root=temp_git_repo,
    )

    diff = (
        "--- a/README.md\n"
        "+++ b/README.md\n"
        "@@ -1 +1,2 @@\n"
        " # Test Repo\n"
        "+PR publication verified\n"
    )

    patch_info = PatchInfo(
        patch_id="task-42",
        patch_content=diff,
        author="Eira Bot",
        summary="Automated PR test verification",
    )

    pr_meta = PRMetadata(
        title="feat: automated update from worktree",
        description="Automated patch applied cleanly",
        branch="feature/automated-pr-42",
        base_branch="main",
    )

    # Mock API call methods
    with patch.object(
        publisher, "create_pull_request", return_value=PRResult(
            pr_number=101,
            pr_url="https://github.com/test-org/test-repo/pull/101",
            status=PRStatus.CREATED,
        )
    ), patch.object(publisher, "add_pr_comment", return_value={"id": 1}):
        grant = MagicMock(spec=VerifiedAuthorityGrant)
        grant.verified = True
        grant.action = "release.publish"
        grant.resource = "repository:test-org/test-repo"
        grant.parameters = (("patch_id", "task-42"), ("base_branch", "main"))
        result = publisher.publish_patch_as_pr(
            patch=patch_info,
            pr_metadata=pr_meta,
            authority_grant=grant,
            test_results={"status": "passed", "tests_run": 1, "failures": 0},
            push_remote=False,  # Local repo without origin
        )

        assert result.status == PRStatus.CREATED
        assert result.pr_number == 101
        assert result.pr_url == "https://github.com/test-org/test-repo/pull/101"
        assert result.commit_hash is not None


def test_git_pr_publisher_rejects_unverified_authority_grant(temp_git_repo: Path):
    """Test security fail-closed gate when unverified authority grant is passed."""
    publisher = GitPRPublisher(
        owner="test-org",
        repo="test-repo",
        token="ghp_testtoken123",
        repo_root=temp_git_repo,
    )

    patch_info = PatchInfo(
        patch_id="task-43",
        patch_content="dummy",
        author="Bad Bot",
    )
    pr_meta = PRMetadata(
        title="feat: malicious",
        description="",
        branch="feature/malicious",
    )

    unverified_grant = MagicMock(spec=VerifiedAuthorityGrant)
    unverified_grant.verified = False

    with pytest.raises(WorktreeSecurityError, match="cryptographic verification"):
        publisher.publish_patch_as_pr(
            patch=patch_info,
            pr_metadata=pr_meta,
            authority_grant=unverified_grant,
            push_remote=False,
        )


def test_git_pr_publisher_requires_authority_and_test_evidence(temp_git_repo: Path):
    publisher = GitPRPublisher(owner="test-org", repo="test-repo", token="token", repo_root=temp_git_repo)
    patch_info = PatchInfo(patch_id="task-44", patch_content="diff", author="bot")
    metadata = PRMetadata(title="test", description="", branch="feature/test")
    with pytest.raises(WorktreeSecurityError, match="required"):
        publisher.publish_patch_as_pr(patch_info, metadata, push_remote=False)
    grant = MagicMock(spec=VerifiedAuthorityGrant)
    grant.verified = True
    grant.action = "release.publish"
    grant.resource = "repository:test-org/test-repo"
    grant.parameters = (("patch_id", "task-44"), ("base_branch", "main"))
    with pytest.raises(WorktreeSecurityError, match="test evidence"):
        publisher.publish_patch_as_pr(patch_info, metadata, authority_grant=grant, push_remote=False)

    grant.parameters = (("patch_id", "another-patch"), ("base_branch", "main"))
    with pytest.raises(WorktreeSecurityError, match="bound to this patch"):
        publisher.publish_patch_as_pr(
            patch_info,
            metadata,
            authority_grant=grant,
            test_results={"status": "passed", "tests_run": 1, "failures": 0},
            push_remote=False,
        )
