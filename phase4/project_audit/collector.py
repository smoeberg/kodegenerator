"""Deterministic read-only collector for project-audit evidence bundles."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .models import (
    EvidenceArtifact,
    EvidenceKind,
    ProjectAuditContractError,
    ProjectEvidenceBundle,
    RepositoryManifest,
)


class EvidenceCollectionError(ProjectAuditContractError):
    """Repository evidence could not be collected without ambiguity."""


class EvidenceLimitError(EvidenceCollectionError):
    """A complete manifest exceeds the collector's configured bounds."""


class EvidenceIntegrityError(EvidenceCollectionError):
    """Observed repository bytes do not match the trusted manifest."""


class ProjectEvidenceCollector:
    """Read and verify an exact external manifest without invoking Git or shell.

    Manifest creation is deliberately outside this component. A trusted caller
    must bind the complete tracked-file list and SHA-256 values to a revision.
    The collector only verifies that the local snapshot exactly matches it.
    """

    def __init__(
        self,
        root: Path,
        *,
        max_files: int = 5_000,
        max_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        if not isinstance(root, Path):
            raise TypeError("root must be a pathlib.Path")
        if type(max_files) is not int or max_files < 1:
            raise ValueError("max_files must be a positive integer")
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes must be a positive integer")
        resolved = root.resolve()
        if not resolved.is_dir():
            raise EvidenceCollectionError("repository root must be a directory")
        self._root = resolved
        self._max_files = max_files
        self._max_bytes = max_bytes

    @property
    def root(self) -> Path:
        return self._root

    def collect(self, manifest: RepositoryManifest) -> ProjectEvidenceBundle:
        if not isinstance(manifest, RepositoryManifest):
            raise TypeError("manifest must be a RepositoryManifest")
        if len(manifest.entries) > self._max_files:
            raise EvidenceLimitError("manifest exceeds the collector file limit")

        artifacts: list[EvidenceArtifact] = []
        total_bytes = 0
        for entry in manifest.entries:
            candidate = self._root.joinpath(*entry.path.split("/"))
            self._reject_symlinks(candidate)
            try:
                resolved = candidate.resolve(strict=True)
            except FileNotFoundError as exc:
                raise EvidenceIntegrityError(
                    f"manifested path is missing: {entry.path}"
                ) from exc
            if not resolved.is_relative_to(self._root) or not resolved.is_file():
                raise EvidenceIntegrityError(
                    f"manifested path is not a regular repository file: {entry.path}"
                )

            data = resolved.read_bytes()
            total_bytes += len(data)
            if total_bytes > self._max_bytes:
                raise EvidenceLimitError("manifest exceeds the collector byte limit")
            actual_sha256 = hashlib.sha256(data).hexdigest()
            if actual_sha256 != entry.sha256:
                raise EvidenceIntegrityError(
                    f"manifest SHA-256 mismatch for {entry.path}"
                )
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                content = None
            artifacts.append(
                EvidenceArtifact(
                    path=entry.path,
                    kind=_kind_for_path(entry.path),
                    sha256=actual_sha256,
                    byte_count=len(data),
                    content=content,
                )
            )
        return ProjectEvidenceBundle(manifest=manifest, artifacts=tuple(artifacts))

    def _reject_symlinks(self, candidate: Path) -> None:
        current = self._root
        for part in candidate.relative_to(self._root).parts:
            current = current / part
            if current.is_symlink():
                raise EvidenceIntegrityError(
                    f"manifested path traverses a symlink: {candidate.relative_to(self._root)}"
                )


def _kind_for_path(path: str) -> EvidenceKind:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if lowered.startswith(("tests/", "test/")) or name.startswith("test_"):
        return EvidenceKind.TEST
    if lowered.startswith(".github/workflows/"):
        return EvidenceKind.CI
    if lowered.startswith("alembic/") or name == "alembic.ini":
        return EvidenceKind.MIGRATION
    if name in {
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "requirements.txt",
    } or lowered.startswith(("deploy/", "deployment/")):
        return EvidenceKind.DEPLOYMENT
    if "requirement" in name or "roadmap" in name:
        return EvidenceKind.REQUIREMENT
    if lowered.startswith("docs/") or name in {"readme.md", "architecture.md"}:
        return EvidenceKind.ARCHITECTURE
    if name.startswith(".env") or name.endswith((".ini", ".toml", ".yaml", ".yml")):
        return EvidenceKind.CONFIGURATION
    if name.endswith((".py", ".js", ".ts", ".tsx", ".jsx")):
        return EvidenceKind.SOURCE
    return EvidenceKind.OTHER
