import subprocess
from pathlib import Path

import pytest

from domain.factory_work import WriteScope
from services.factory_workspace import FactoryWorkspaceError, FactoryWorkspaceManager
from services.side_effects import SideEffectCoordinator


def git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.test")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("VALUE = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "base")
    return root, git(root, "rev-parse", "HEAD")


def test_exact_base_workspace_attests_and_preserves_branch(tmp_path: Path) -> None:
    root, base = repository(tmp_path)
    manager = FactoryWorkspaceManager(root)
    workspace = manager.create(
        execution_id="exec-1", candidate_id="candidate-1", base_sha=base
    )
    (workspace.path / "src" / "app.py").write_text("VALUE = 2\n")
    git(workspace.path, "add", ".")
    git(workspace.path, "commit", "-m", "candidate")
    evidence = manager.attest(workspace, WriteScope(("src",)))
    assert evidence["base_sha"] == base
    assert evidence["affected_paths"] == ("src/app.py",)
    assert evidence["branch"] == "factory/exec-1/candidate-1"
    manager.cleanup(workspace)
    assert git(root, "branch", "--list", evidence["branch"])


def test_out_of_scope_change_fails_closed(tmp_path: Path) -> None:
    root, base = repository(tmp_path)
    manager = FactoryWorkspaceManager(root)
    workspace = manager.create(
        execution_id="exec-2", candidate_id="candidate-2", base_sha=base
    )
    (workspace.path / "README.md").write_text("outside\n")
    git(workspace.path, "add", ".")
    git(workspace.path, "commit", "-m", "outside")
    with pytest.raises(FactoryWorkspaceError, match="outside write scope"):
        manager.attest(workspace, WriteScope(("src",)))
    manager.cleanup(workspace)


def test_publish_reconciles_existing_identical_remote_branch(tmp_path: Path) -> None:
    root, base = repository(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True)
    git(root, "remote", "add", "origin", str(remote))
    manager = FactoryWorkspaceManager(root)
    workspace = manager.create(
        execution_id="exec-3", candidate_id="candidate-3", base_sha=base
    )
    (workspace.path / "src" / "app.py").write_text("VALUE = 3\n")
    git(workspace.path, "add", ".")
    git(workspace.path, "commit", "-m", "candidate")
    first, replayed = manager.publish(
        workspace,
        organization_id="org-1",
        coordinator=SideEffectCoordinator(),
    )
    assert not replayed and not first["reconciled"]
    reconciled, replayed = manager.publish(
        workspace,
        organization_id="org-1",
        coordinator=SideEffectCoordinator(),
    )
    assert not replayed and reconciled["reconciled"]
    assert reconciled["head_sha"] == first["head_sha"]
    manager.cleanup(workspace)


def _create_and_clean(args: tuple[str, str, int]) -> str:
    root, base, worker = args
    manager = FactoryWorkspaceManager(root)
    created = []
    for n in range(5):
        workspace = manager.create(
            execution_id=f"exec-{worker}", candidate_id=f"candidate-{n}", base_sha=base
        )
        created.append(workspace)
    for workspace in created[:2]:
        manager.cleanup(workspace)
    return ",".join(item.branch for item in created)


def test_parallel_processes_create_and_clean_worktrees_safely(tmp_path: Path) -> None:
    """Git cannot run worktree administration concurrently in one repository.

    Workers run as separate processes, so the manager must serialize across
    processes and not only across threads (regression: "failed to read
    .git/worktrees/<name>/commondir").
    """
    import multiprocessing

    root, base = repository(tmp_path)
    context = multiprocessing.get_context("spawn")
    with context.Pool(4) as pool:
        results = pool.map(_create_and_clean, [(str(root), base, w) for w in range(4)])

    branches = [branch for result in results for branch in result.split(",")]
    assert len(set(branches)) == 20
    listed = git(root, "worktree", "list", "--porcelain").count("worktree ")
    assert listed == 1 + 4 * 3  # main checkout + three kept per worker
    assert git(root, "worktree", "prune", "--dry-run") == ""


def test_managers_for_one_repository_share_the_admin_lock(tmp_path: Path) -> None:
    root, _ = repository(tmp_path)
    first = FactoryWorkspaceManager(root)
    second = FactoryWorkspaceManager(root / "src" / "..")
    assert first._admin_lock is second._admin_lock
    assert first._admin_lock_path == root.resolve() / ".git" / "dor-worktree-admin.lock"
