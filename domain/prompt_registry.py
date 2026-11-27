"""Prompts are versioned data, not code (completion plan, decision 42).

Every agent role gets its instructions for one purpose from a file::

    config/prompts/<role>/<purpose>.v<N>.md

with a YAML header (role, purpose, version, status, approved_by,
approval_ref, author) and the prompt text. The lifecycle follows the house
rules: ``proposed`` → ``trial`` → ``active`` → ``retired``. The prompt
producer writes new versions as ``proposed``; the prompt reviewer, from
another producer, challenges them; the project board approves by merging
the change that makes a version ``trial`` or ``active``.

Loading fails closed: the role must be an agent role in the role catalog,
a ``trial`` or ``active`` version needs an approval by a deciding role, and
each role and purpose in use has exactly one active version and at most one
on trial (a purpose whose versions are all retired is out of use). A prompt's identity on every job record is ``role/purpose@vN``
plus the fingerprint of its text, so statistics can be kept per prompt
version.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

from domain.role_process import RoleAuthority, RoleCatalog, RoleKind, default_catalog

PROMPTS_PATH = Path(__file__).resolve().parents[1] / "config" / "prompts"
_FILE = re.compile(r"^(?P<purpose>[a-z][a-z0-9_]*)\.v(?P<version>[1-9][0-9]*)\.md$")
_ID = re.compile(r"^[a-z][a-z0-9_]*$")


class PromptRegistryError(ValueError):
    """The prompt registry is inconsistent or a prompt is missing."""


class PromptStatus(str, Enum):
    PROPOSED = "proposed"
    TRIAL = "trial"
    ACTIVE = "active"
    RETIRED = "retired"


@dataclass(frozen=True)
class PromptVersion:
    role: str
    purpose: str
    version: int
    status: PromptStatus
    text: str
    approved_by: str | None
    approval_ref: str | None
    author: str | None
    path: Path

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def ref(self) -> str:
        """The prompt version as it is written on a job record."""
        return f"{self.role}/{self.purpose}@v{self.version}+{self.fingerprint[:12]}"


def parse_prompt_file(path: Path) -> PromptVersion:
    match = _FILE.match(path.name)
    if not match:
        raise PromptRegistryError(f"{path}: name must be <purpose>.v<N>.md")
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n") or "\n---\n" not in raw[4:]:
        raise PromptRegistryError(f"{path}: missing YAML header")
    header_text, text = raw[4:].split("\n---\n", 1)
    try:
        header = yaml.safe_load(header_text) or {}
    except yaml.YAMLError as exc:
        raise PromptRegistryError(f"{path}: invalid header: {exc}") from exc
    try:
        prompt = PromptVersion(
            role=str(header["role"]),
            purpose=str(header["purpose"]),
            version=int(header["version"]),
            status=PromptStatus(header["status"]),
            text=text.strip() + "\n",
            approved_by=header.get("approved_by"),
            approval_ref=header.get("approval_ref"),
            author=header.get("author"),
            path=path,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PromptRegistryError(f"{path}: invalid header: {exc}") from exc
    if (prompt.role, prompt.purpose, prompt.version) != (
        path.parent.name,
        match["purpose"],
        int(match["version"]),
    ):
        raise PromptRegistryError(f"{path}: header does not match the file name")
    if not prompt.text.strip():
        raise PromptRegistryError(f"{path}: empty prompt")
    return prompt


class PromptRegistry:
    def __init__(self, prompts: list[PromptVersion], catalog: RoleCatalog) -> None:
        self._catalog = catalog
        self._by_key: dict[tuple[str, str], list[PromptVersion]] = {}
        deciders = {
            r.id for r in catalog.roles.values() if r.authority is RoleAuthority.DECIDES
        }
        for prompt in prompts:
            if not (_ID.match(prompt.role) and _ID.match(prompt.purpose)):
                raise PromptRegistryError(f"{prompt.path}: invalid role or purpose id")
            spec = catalog.roles.get(prompt.role)
            if spec is None or spec.kind is not RoleKind.AGENT:
                raise PromptRegistryError(
                    f"{prompt.path}: {prompt.role} is not an agent role in the catalog"
                )
            if prompt.status in {PromptStatus.TRIAL, PromptStatus.ACTIVE} and (
                prompt.approved_by not in deciders or not prompt.approval_ref
            ):
                raise PromptRegistryError(
                    f"{prompt.path}: a {prompt.status.value} prompt needs the project "
                    "board's approval and a reference to it"
                )
            self._by_key.setdefault((prompt.role, prompt.purpose), []).append(prompt)
        for (role, purpose), versions in self._by_key.items():
            numbers = [p.version for p in versions]
            if len(numbers) != len(set(numbers)):
                raise PromptRegistryError(f"{role}/{purpose}: duplicate version")
            active = [p for p in versions if p.status is PromptStatus.ACTIVE]
            trial = [p for p in versions if p.status is PromptStatus.TRIAL]
            if all(p.status is PromptStatus.RETIRED for p in versions):
                versions.sort(key=lambda p: p.version)
                continue
            if len(active) != 1:
                raise PromptRegistryError(
                    f"{role}/{purpose}: needs exactly one active version, has {len(active)}"
                )
            if len(trial) > 1:
                raise PromptRegistryError(
                    f"{role}/{purpose}: more than one version on trial"
                )
            versions.sort(key=lambda p: p.version)

    @classmethod
    def load(
        cls, root: Path = PROMPTS_PATH, catalog: RoleCatalog | None = None
    ) -> PromptRegistry:
        files = sorted(root.glob("*/*.md")) if root.exists() else []
        return cls([parse_prompt_file(f) for f in files], catalog or default_catalog())

    def active(self, role: str, purpose: str) -> PromptVersion:
        versions = self._by_key.get((role, purpose))
        if not versions:
            raise PromptRegistryError(f"no prompt for {role}/{purpose}")
        active = next((p for p in versions if p.status is PromptStatus.ACTIVE), None)
        if active is None:
            raise PromptRegistryError(f"{role}/{purpose} is retired; no active prompt")
        return active

    def trial(self, role: str, purpose: str) -> PromptVersion | None:
        return next(
            (
                p
                for p in self._by_key.get((role, purpose), [])
                if p.status is PromptStatus.TRIAL
            ),
            None,
        )

    def versions(self, role: str, purpose: str) -> list[PromptVersion]:
        return list(self._by_key.get((role, purpose), []))

    def purposes(self) -> list[tuple[str, str]]:
        return sorted(self._by_key)

    def next_version(self, role: str, purpose: str) -> int:
        return (
            max((p.version for p in self._by_key.get((role, purpose), [])), default=0)
            + 1
        )


_DEFAULT: PromptRegistry | None = None


def default_registry() -> PromptRegistry:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = PromptRegistry.load()
    return _DEFAULT


def prompt(role: str, purpose: str) -> PromptVersion:
    """The active prompt for a role and purpose; fails closed when missing."""
    return default_registry().active(role, purpose)
