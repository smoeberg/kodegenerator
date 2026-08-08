"""Trusted Git manifest construction for the Project Audit application layer.

The evidence collector deliberately knows nothing about Git.  This module is
the narrow application boundary that proves which tracked files belong to a
revision and that the working-tree bytes still match that revision before the
collector reads them.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .models import ManifestEntry, RepositoryManifest


class GitRepositoryError(RuntimeError):
    """A repository revision could not be resolved without ambiguity."""


class GitRepositoryDriftError(GitRepositoryError):
    """Tracked working-tree bytes differ from the requested revision."""


class GitRepositoryManifestBuilder:
    """Build a complete manifest for a clean, checked-out Git revision.

    Only read-only Git commands are invoked. Untracked files are intentionally
    excluded because they are not part of the content-addressed revision.
    """

    def __init__(self, root: Path) -> None:
        if not isinstance(root, Path):
            raise TypeError("root must be a pathlib.Path")
        resolved = root.resolve()
        if not resolved.is_dir():
            raise GitRepositoryError("repository root must be a directory")
        self._root = resolved
        top_level = self._git_text("rev-parse", "--show-toplevel").strip()
        if Path(top_level).resolve() != resolved:
            raise GitRepositoryError("root must be the Git repository top level")

    @property
    def root(self) -> Path:
        return self._root

    def build(
        self,
        *,
        repository: str,
        revision: str = "HEAD",
    ) -> RepositoryManifest:
        if not isinstance(repository, str) or not repository.strip():
            raise ValueError("repository must be a non-empty string")
        if (
            not isinstance(revision, str)
            or not revision.strip()
            or revision != revision.strip()
            or "\x00" in revision
            or "\n" in revision
        ):
            raise ValueError("revision must be a canonical non-empty Git revision")

        commit_sha = self._git_text(
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{revision}^{{commit}}",
        ).strip()
        drift = self._git(
            "diff",
            "--quiet",
            "--no-ext-diff",
            commit_sha,
            "--",
            check=False,
        )
        if drift.returncode == 1:
            raise GitRepositoryDriftError(
                "tracked working tree does not match the requested revision"
            )
        if drift.returncode != 0:
            raise GitRepositoryError(
                "Git could not compare the working tree to the requested revision"
            )

        raw_paths = self._git(
            "ls-tree",
            "-r",
            "-z",
            "--name-only",
            "--full-tree",
            commit_sha,
        ).stdout
        try:
            paths = tuple(
                item.decode("utf-8") for item in raw_paths.split(b"\x00") if item
            )
        except UnicodeDecodeError as exc:
            raise GitRepositoryError(
                "tracked repository paths must be valid UTF-8"
            ) from exc
        if not paths:
            raise GitRepositoryError("requested revision contains no tracked files")

        entries: list[ManifestEntry] = []
        for path in paths:
            candidate = self._root.joinpath(*path.split("/"))
            try:
                data = candidate.read_bytes()
            except (FileNotFoundError, IsADirectoryError, OSError) as exc:
                raise GitRepositoryDriftError(
                    f"tracked path cannot be read from the working tree: {path}"
                ) from exc
            entries.append(
                ManifestEntry(path=path, sha256=hashlib.sha256(data).hexdigest())
            )

        return RepositoryManifest(
            repository=repository,
            commit_sha=commit_sha,
            entries=tuple(entries),
        )

    def _git_text(self, *args: str) -> str:
        try:
            return self._git(*args).stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitRepositoryError("Git returned non-UTF-8 metadata") from exc

    def _git(
        self,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[bytes]:
        try:
            return subprocess.run(
                ("git", "-C", str(self._root), *args),
                check=check,
                capture_output=True,
            )
        except FileNotFoundError as exc:
            raise GitRepositoryError("Git executable is unavailable") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise GitRepositoryError(detail or "Git command failed") from exc
