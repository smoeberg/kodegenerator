# domain/role_process.py
"""Role-process logic: the foundation principle of DOR.

Completion plan, decision 39. The process is a fixed chain of roles; agents
are interchangeable and are assigned to roles per job. A role is a prompt
plus a context packet in a fresh job, so any agent may hold any role. What
the foundation enforces is independence where it matters:

* every output of an agent role is controlled by another role before it
  goes on;
* on the same work package, an agent holding a control role must come from
  a different producer (brand) than the agent whose output it controls;
* the control runs in a new session, never in the controlled agent's session.

The catalog is data (``config/role_process/catalog.v1.yaml``). Loading it
and validating an assignment both fail closed.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

CATALOG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "role_process" / "catalog.v1.yaml"
)

#: Independence level required between a control role and the role it
#: controls. Matches ``phase4.council.configuration.IndependenceLevel.BRAND``:
#: the model producer (anthropic, openai, mistral, ...), not the API adapter.
REQUIRED_INDEPENDENCE_LEVEL = "brand"


class RoleProcessError(ValueError):
    """Raised when the catalog is invalid or an assignment breaks the principle."""


class RoleKind(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True)
class RoleSpec:
    id: str
    name: str
    kind: RoleKind
    input: str
    output: str
    controlled_by: tuple[str, ...]


@dataclass(frozen=True)
class RoleCatalog:
    version: int
    roles: Mapping[str, RoleSpec]
    pipeline_task_roles: Mapping[str, str]
    fingerprint: str

    def role(self, role_id: str) -> RoleSpec:
        try:
            return self.roles[role_id]
        except KeyError as exc:
            raise RoleProcessError(f"unknown role: {role_id}") from exc

    def role_for_task_type(self, task_type: str) -> RoleSpec:
        role_id = self.pipeline_task_roles.get(task_type)
        if role_id is None:
            raise RoleProcessError(f"pipeline task type has no role: {task_type}")
        return self.role(role_id)

    def controls(self, controller_id: str, controlled_id: str) -> bool:
        return controller_id in self.role(controlled_id).controlled_by


@dataclass(frozen=True)
class RoleAssignment:
    """Who holds a role in one job on one work package."""

    job_id: str
    work_package_id: str
    role_id: str
    brand: str | None
    session_id: str | None


def _fingerprint(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def parse_catalog(data: Mapping[str, Any]) -> RoleCatalog:
    """Build and validate a catalog; any inconsistency fails closed."""
    if not isinstance(data, Mapping):
        raise RoleProcessError("role catalog must be a mapping")
    if data.get("independence_level") != REQUIRED_INDEPENDENCE_LEVEL:
        raise RoleProcessError(
            f"independence_level must be {REQUIRED_INDEPENDENCE_LEVEL!r}"
        )
    version = data.get("catalog_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise RoleProcessError("catalog_version must be a positive integer")

    roles: dict[str, RoleSpec] = {}
    for raw in data.get("roles") or []:
        try:
            spec = RoleSpec(
                id=str(raw["id"]),
                name=str(raw["name"]),
                kind=RoleKind(raw["kind"]),
                input=str(raw["input"]),
                output=str(raw["output"]),
                controlled_by=tuple(raw.get("controlled_by") or ()),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RoleProcessError(f"invalid role entry: {exc}") from exc
        if spec.id in roles:
            raise RoleProcessError(f"duplicate role: {spec.id}")
        roles[spec.id] = spec
    if not roles:
        raise RoleProcessError("role catalog has no roles")

    for spec in roles.values():
        unknown = [c for c in spec.controlled_by if c not in roles]
        if unknown:
            raise RoleProcessError(
                f"{spec.id} is controlled by unknown roles: {unknown}"
            )
        if spec.id in spec.controlled_by:
            raise RoleProcessError(f"{spec.id} must not control itself")
        if spec.kind is RoleKind.AGENT:
            if not spec.controlled_by:
                raise RoleProcessError(
                    f"agent role {spec.id} has no controlling role; "
                    "no agent output may go on uncontrolled"
                )
            if "fact_check" not in spec.controlled_by:
                raise RoleProcessError(
                    f"agent role {spec.id} must be controlled by fact_check"
                )

    task_roles = dict(data.get("pipeline_task_roles") or {})
    for task_type, role_id in task_roles.items():
        if role_id not in roles:
            raise RoleProcessError(
                f"task type {task_type} maps to unknown role {role_id}"
            )

    return RoleCatalog(
        version=version,
        roles=roles,
        pipeline_task_roles=task_roles,
        fingerprint=_fingerprint(dict(data)),
    )


def load_catalog(path: Path = CATALOG_PATH) -> RoleCatalog:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RoleProcessError(f"cannot read role catalog {path}: {exc}") from exc
    return parse_catalog(data)


_DEFAULT: RoleCatalog | None = None


def default_catalog() -> RoleCatalog:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = load_catalog()
    return _DEFAULT


def validate_assignment(
    catalog: RoleCatalog,
    assignment: RoleAssignment,
    others_on_package: Iterable[RoleAssignment],
) -> None:
    """Fail closed when an assignment breaks the role-process principle.

    For every assignment on the same work package whose output this role
    controls (or that controls this role's output), the producer must differ
    and the session must differ. An agent role without a known producer or
    session cannot be checked and is rejected.
    """
    spec = catalog.role(assignment.role_id)
    if spec.kind is not RoleKind.AGENT:
        return
    if not assignment.brand or not assignment.session_id:
        raise RoleProcessError(
            f"agent role {spec.id} needs a known producer (brand) and session"
        )
    for other in others_on_package:
        if other.job_id == assignment.job_id:
            continue
        if other.work_package_id != assignment.work_package_id:
            continue
        related = catalog.controls(
            assignment.role_id, other.role_id
        ) or catalog.controls(other.role_id, assignment.role_id)
        if not related:
            continue
        if catalog.role(other.role_id).kind is RoleKind.AGENT and (
            not other.brand or not other.session_id
        ):
            raise RoleProcessError(
                f"{other.role_id} on {assignment.work_package_id} has no known producer "
                "or session; independence cannot be verified"
            )
        if other.session_id and other.session_id == assignment.session_id:
            raise RoleProcessError(
                f"{assignment.role_id} and {other.role_id} on {assignment.work_package_id} "
                "must not share a session"
            )
        if other.brand and other.brand.casefold() == assignment.brand.casefold():
            raise RoleProcessError(
                f"{assignment.role_id} and {other.role_id} on {assignment.work_package_id} "
                f"must come from different producers (both {assignment.brand})"
            )
