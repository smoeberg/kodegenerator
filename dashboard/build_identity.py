"""Deterministic build identity for the DOR runtime and dashboard."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REVISION_FILE = ".dor-build-revision"
_FINGERPRINT_FILE = ".dor-build-fingerprint"
_IGNORED_DIR_NAMES = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "ENV",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "venv",
}
_IGNORED_FILE_NAMES = {
    _REVISION_FILE,
    _FINGERPRINT_FILE,
    ".coverage",
    ".DS_Store",
}
_IGNORED_SUFFIXES = {".db", ".pyc", ".pyd", ".pyo"}


@dataclass(frozen=True)
class BuildIdentity:
    revision: str | None
    fingerprint: str

    @property
    def short_revision(self) -> str | None:
        return self.revision[:12] if self.revision else None

    @property
    def short_fingerprint(self) -> str:
        return self.fingerprint[:12]


def _included_source_file(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in _IGNORED_DIR_NAMES for part in relative.parts[:-1]):
        return False
    if relative.name in _IGNORED_FILE_NAMES or relative.name.startswith(".env"):
        return False
    return relative.suffix not in _IGNORED_SUFFIXES


def source_fingerprint(root: Path) -> str:
    """Hash source paths and bytes while excluding transient/local-only files."""
    root = root.resolve()
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
        if not path.is_file() or not _included_source_file(path, root):
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_value(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not value or value.lower() in {"unknown", "none", "null", "-"}:
        return None
    return value


def _git_revision(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def resolve_build_identity(root: Path | None = None) -> BuildIdentity:
    root = (root or Path(__file__).resolve().parents[1]).resolve()

    revision = _read_value(root / _REVISION_FILE)
    if revision is None:
        revision = os.environ.get("DOR_BUILD_REVISION", "").strip() or None
    if revision is None:
        revision = _git_revision(root)

    fingerprint = _read_value(root / _FINGERPRINT_FILE)
    if fingerprint is None:
        fingerprint = source_fingerprint(root)

    return BuildIdentity(revision=revision, fingerprint=fingerprint)


@lru_cache(maxsize=1)
def current_build_identity() -> BuildIdentity:
    return resolve_build_identity()


def write_build_metadata(root: Path, revision: str | None = None) -> BuildIdentity:
    """Bake source identity into an image without requiring .git in the build context."""
    root = root.resolve()
    fingerprint = source_fingerprint(root)
    normalized_revision = (revision or "").strip()
    if not normalized_revision:
        normalized_revision = "unknown"

    (root / _FINGERPRINT_FILE).write_text(f"{fingerprint}\n", encoding="utf-8")
    (root / _REVISION_FILE).write_text(f"{normalized_revision}\n", encoding="utf-8")
    return BuildIdentity(
        revision=None if normalized_revision.lower() == "unknown" else normalized_revision,
        fingerprint=fingerprint,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Generate DOR build metadata.")
    parser.add_argument("--write-build-metadata", type=Path, metavar="ROOT")
    parser.add_argument(
        "--revision",
        default=os.environ.get("DOR_BUILD_REVISION", "unknown"),
        help="Git/source revision to bake into the image.",
    )
    args = parser.parse_args()
    if args.write_build_metadata is None:
        parser.error("--write-build-metadata is required")
    identity = write_build_metadata(args.write_build_metadata, args.revision)
    revision = identity.short_revision or "unknown"
    print(f"DOR build={identity.short_fingerprint} revision={revision}")


if __name__ == "__main__":
    _main()
