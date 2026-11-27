"""Exact-base isolated candidate worktrees and fenced branch publication."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:  # POSIX; DOR runs on Linux. Without it only the in-process lock applies.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]

from domain.factory_work import WriteScope, fingerprint

from .side_effects import SideEffectCoordinator

_SHA = re.compile(r"^[a-f0-9]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")

# Git does not support concurrent `worktree add/remove/prune` or branch
# creation in one repository: parallel calls can read another call's
# half-written `.git/worktrees/*` files ("failed to read ... commondir").
# These operations are therefore serialized per repository, in-process with a
# thread lock and across processes with an advisory lock in the git dir.
_ADMIN_LOCKS: dict[Path, threading.Lock] = {}
_ADMIN_LOCKS_GUARD = threading.Lock()


class FactoryWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateWorkspace:
    execution_id: str
    candidate_id: str
    base_sha: str
    branch: str
    path: Path


class FactoryWorkspaceManager:
    def __init__(self, repository: str | Path) -> None:
        self._repository = Path(repository).resolve()
        common_dir = Path(self._git("rev-parse", "--git-common-dir").strip())
        if not common_dir.is_absolute():
            common_dir = (self._repository / common_dir).resolve()
        self._admin_lock_path = common_dir / "dor-worktree-admin.lock"
        with _ADMIN_LOCKS_GUARD:
            self._admin_lock = _ADMIN_LOCKS.setdefault(common_dir, threading.Lock())

    @contextmanager
    def _repository_admin(self) -> Iterator[None]:
        """Serialize git operations that change shared repository metadata."""
        with self._admin_lock:
            if fcntl is None:
                yield
                return
            with open(self._admin_lock_path, "a+") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def create(
        self, *, execution_id: str, candidate_id: str, base_sha: str
    ) -> CandidateWorkspace:
        if not _ID.fullmatch(execution_id) or not _ID.fullmatch(candidate_id):
            raise FactoryWorkspaceError("execution and candidate IDs must be canonical")
        if not _SHA.fullmatch(base_sha):
            raise FactoryWorkspaceError("base SHA must be an exact Git SHA-1")
        resolved = self._git("rev-parse", f"{base_sha}^{{commit}}").strip()
        if resolved != base_sha:
            raise FactoryWorkspaceError("base SHA did not resolve exactly")
        branch = f"factory/{execution_id}/{candidate_id}".lower().replace(":", "-")
        path = Path(tempfile.mkdtemp(prefix="dor-candidate-"))
        try:
            with self._repository_admin():
                if self._git("branch", "--list", branch).strip():
                    raise FactoryWorkspaceError("candidate branch already exists")
                self._git("worktree", "add", "-b", branch, str(path), base_sha)
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            raise
        return CandidateWorkspace(execution_id, candidate_id, base_sha, branch, path)

    def attest(self, workspace: CandidateWorkspace, scope: WriteScope) -> dict:
        head = self._git_at(workspace.path, "rev-parse", "HEAD").strip()
        paths = tuple(
            sorted(
                filter(
                    None,
                    self._git_at(
                        workspace.path, "diff", "--name-only", workspace.base_sha, head
                    ).splitlines(),
                )
            )
        )
        self._validate_paths(paths, scope)
        commits = tuple(
            filter(
                None,
                self._git_at(
                    workspace.path,
                    "rev-list",
                    "--reverse",
                    f"{workspace.base_sha}..{head}",
                ).splitlines(),
            )
        )
        if not commits:
            raise FactoryWorkspaceError("candidate contains no commits")
        patch = self._git_at(
            workspace.path, "diff", "--binary", workspace.base_sha, head
        )
        return {
            "branch": workspace.branch,
            "base_sha": workspace.base_sha,
            "head_sha": head,
            "commit_shas": commits,
            "affected_paths": paths,
            "patch_fingerprint": fingerprint(patch),
        }

    def publish(
        self,
        workspace: CandidateWorkspace,
        *,
        organization_id: str,
        coordinator: SideEffectCoordinator,
        remote: str = "origin",
    ) -> tuple[dict, bool]:
        request = {
            "repository": str(self._repository),
            "remote": remote,
            "branch": workspace.branch,
            "base_sha": workspace.base_sha,
            "head_sha": self._git_at(workspace.path, "rev-parse", "HEAD").strip(),
        }
        return coordinator.execute(
            organization_id=organization_id,
            action="factory.candidate.push",
            idempotency_key=f"candidate-push:{workspace.candidate_id}",
            request_data=request,
            operation=lambda: self._push(workspace, remote, request["head_sha"]),
        )

    def cleanup(
        self, workspace: CandidateWorkspace, *, discard_branch: bool = False
    ) -> None:
        """Remove the worktree; ``discard_branch`` also drops a rejected candidate."""
        with self._repository_admin():
            try:
                self._git("worktree", "remove", "--force", str(workspace.path))
            finally:
                shutil.rmtree(workspace.path, ignore_errors=True)
                self._git("worktree", "prune")
                if discard_branch:
                    self._git("branch", "-D", workspace.branch)

    def _push(self, workspace: CandidateWorkspace, remote: str, head_sha: str) -> dict:
        existing = self._git_at(
            workspace.path,
            "ls-remote",
            "--heads",
            remote,
            f"refs/heads/{workspace.branch}",
        ).strip()
        if existing:
            remote_head = existing.split()[0]
            if remote_head != head_sha:
                raise FactoryWorkspaceError(
                    "candidate branch exists at a different commit"
                )
            return {
                "branch": workspace.branch,
                "head_sha": head_sha,
                "reconciled": True,
            }
        self._git_at(
            workspace.path, "push", remote, f"HEAD:refs/heads/{workspace.branch}"
        )
        return {
            "branch": workspace.branch,
            "head_sha": head_sha,
            "reconciled": False,
        }

    @staticmethod
    def _validate_paths(paths: tuple[str, ...], scope: WriteScope) -> None:
        for path in paths:
            if any(
                path == denied or path.startswith(denied.rstrip("/") + "/")
                for denied in scope.denied_paths
            ):
                raise FactoryWorkspaceError(f"candidate changed denied path: {path}")
            if not any(
                path == allowed or path.startswith(allowed.rstrip("/") + "/")
                for allowed in scope.allowed_paths
            ):
                raise FactoryWorkspaceError(
                    f"candidate changed path outside write scope: {path}"
                )

    def _git(self, *args: str) -> str:
        return self._git_at(self._repository, *args)

    @staticmethod
    def _git_at(path: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=path, text=True, capture_output=True, check=False
        )
        if result.returncode:
            raise FactoryWorkspaceError(result.stderr.strip() or "git command failed")
        return result.stdout
