"""Governed project aggregate for the first-party Control Plane."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

CONTROL_PLANE_CONTRACT_VERSION = "1.0"
MAX_INTENT_BYTES = 64 * 1024


class ProjectContractError(ValueError):
    """Raised when a project command contains invalid or unsafe data."""


class ProjectStateError(RuntimeError):
    """Raised when a project cannot accept the requested transition."""


class ProjectFingerprintError(RuntimeError):
    """Raised when a caller attempts to act on a different project snapshot."""


class ProjectStatus(str, Enum):
    CREATED = "created"
    LAUNCH_REQUESTED = "launch_requested"


def _normalize_json(value: Any, *, path: str = "constraints") -> Any:
    """Return a JSON-safe copy and reject ambiguous or non-finite values."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProjectContractError(f"{path} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ProjectContractError(f"{path} keys must be non-empty strings")
            normalized[key] = _normalize_json(item, path=f"{path}.{key}")
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            _normalize_json(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise ProjectContractError(f"{path} contains a non-JSON value")


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProjectContractError("Project content must be canonical JSON") from exc


def _freeze_json(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _require_text(name: str, value: str, *, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ProjectContractError(f"{name} must be a non-empty trimmed string")
    if len(value) > max_length:
        raise ProjectContractError(f"{name} exceeds {max_length} characters")
    return value


@dataclass(frozen=True)
class ProjectIntent:
    """Immutable intent snapshot captured before planning or execution."""

    goal: str
    description: str = ""
    priority: str = "medium"
    constraints: Mapping[str, Any] | None = None
    required_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text("goal", self.goal, max_length=2_000)
        if not isinstance(self.description, str) or len(self.description) > 20_000:
            raise ProjectContractError("description exceeds 20000 characters")
        if self.priority not in {"low", "medium", "high", "critical"}:
            raise ProjectContractError("priority is not canonical")
        capabilities = tuple(self.required_capabilities)
        if len(capabilities) > 64 or len(set(capabilities)) != len(capabilities):
            raise ProjectContractError(
                "required_capabilities must contain at most 64 unique values"
            )
        for capability in capabilities:
            _require_text("required capability", capability, max_length=128)
            if "." not in capability:
                raise ProjectContractError(
                    "required capabilities must use dot-separated names"
                )
        normalized = _normalize_json(dict(self.constraints or {}))
        object.__setattr__(self, "constraints", _freeze_json(normalized))
        object.__setattr__(self, "required_capabilities", capabilities)
        if (
            len(_canonical_json(self.canonical_dict()).encode("utf-8"))
            > MAX_INTENT_BYTES
        ):
            raise ProjectContractError(
                f"canonical intent exceeds {MAX_INTENT_BYTES} bytes"
            )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "goal": self.goal,
            "description": self.description,
            "priority": self.priority,
            "constraints": _normalize_json(dict(self.constraints or {})),
            "required_capabilities": list(self.required_capabilities),
        }

    @property
    def fingerprint(self) -> str:
        return _sha256(self.canonical_dict())


@dataclass(frozen=True)
class Project:
    """Persistent organization-scoped project state."""

    id: str
    organization_id: str
    name: str
    description: str
    intent: ProjectIntent
    status: ProjectStatus
    created_by: str
    created_at: datetime
    updated_at: datetime
    launched_by: str | None = None
    launched_at: datetime | None = None
    launch_request_fingerprint: str | None = None
    launch_command_id: str | None = None
    revision: int = 0
    contract_version: str = CONTROL_PLANE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProjectStatus):
            raise ProjectContractError("project status is not canonical")
        if not isinstance(self.intent, ProjectIntent):
            raise ProjectContractError("project intent is not canonical")
        for name, value in (
            ("created_at", self.created_at),
            ("updated_at", self.updated_at),
        ):
            if not isinstance(value, datetime):
                raise ProjectContractError(f"{name} must be a datetime")
        _require_text("project id", self.id, max_length=128)
        _require_text("organization id", self.organization_id, max_length=128)
        _require_text("project name", self.name, max_length=255)
        if not isinstance(self.description, str) or len(self.description) > 20_000:
            raise ProjectContractError("project description exceeds 20000 characters")
        _require_text("created_by", self.created_by, max_length=128)
        if self.contract_version != CONTROL_PLANE_CONTRACT_VERSION:
            raise ProjectContractError("unsupported project contract version")
        if self.revision < 0:
            raise ProjectContractError("project revision cannot be negative")
        launch_fields = (
            self.launched_by,
            self.launched_at,
            self.launch_request_fingerprint,
            self.launch_command_id,
        )
        if self.status is ProjectStatus.CREATED and any(launch_fields):
            raise ProjectContractError(
                "created projects cannot contain launch metadata"
            )
        if self.status is ProjectStatus.CREATED and self.revision != 0:
            raise ProjectContractError("created projects must have revision zero")
        if self.status is ProjectStatus.LAUNCH_REQUESTED:
            if any(item is None for item in launch_fields):
                raise ProjectContractError(
                    "launch-requested projects require complete launch metadata"
                )
            if self.revision != 1:
                raise ProjectContractError(
                    "launch-requested projects must have revision one"
                )
            if not isinstance(self.launched_at, datetime):
                raise ProjectContractError("launched_at must be a datetime")
            _require_text("launched_by", self.launched_by or "", max_length=128)
            fingerprint = self.launch_request_fingerprint or ""
            if len(fingerprint) != 64 or any(
                character not in "0123456789abcdef" for character in fingerprint
            ):
                raise ProjectContractError(
                    "launch_request_fingerprint must be lowercase SHA-256"
                )
            _require_text(
                "launch_command_id",
                self.launch_command_id or "",
                max_length=128,
            )
            expected = self._launch_fingerprint(
                actor_id=self.launched_by or "",
                command_id=self.launch_command_id or "",
            )
            if fingerprint != expected:
                raise ProjectContractError(
                    "launch request fingerprint does not match project provenance"
                )

    @classmethod
    def create(
        cls,
        *,
        project_id: str,
        organization_id: str,
        name: str,
        description: str,
        intent: ProjectIntent,
        actor_id: str,
        timestamp: datetime | None = None,
    ) -> "Project":
        now = timestamp or datetime.now(timezone.utc)
        return cls(
            id=project_id,
            organization_id=organization_id,
            name=name,
            description=description,
            intent=intent,
            status=ProjectStatus.CREATED,
            created_by=actor_id,
            created_at=now,
            updated_at=now,
        )

    def immutable_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "project_id": self.id,
            "organization_id": self.organization_id,
            "name": self.name,
            "description": self.description,
            "intent": self.intent.canonical_dict(),
            "intent_fingerprint": self.intent.fingerprint,
            "created_by": self.created_by,
            "created_at": _timestamp(self.created_at),
        }

    @property
    def fingerprint(self) -> str:
        """Fingerprint immutable project content, independent of mutable status."""
        return _sha256(self.immutable_dict())

    def _launch_fingerprint(self, *, actor_id: str, command_id: str) -> str:
        return _sha256(
            {
                "contract_version": self.contract_version,
                "command_type": "LaunchProjectCommand",
                "command_id": command_id,
                "organization_id": self.organization_id,
                "project_id": self.id,
                "project_fingerprint": self.fingerprint,
                "requested_by": actor_id,
            }
        )

    def request_launch(
        self,
        *,
        actor_id: str,
        command_id: str,
        expected_project_fingerprint: str,
        timestamp: datetime | None = None,
    ) -> "Project":
        if self.status is not ProjectStatus.CREATED:
            raise ProjectStateError("project is not in the created state")
        if expected_project_fingerprint != self.fingerprint:
            raise ProjectFingerprintError(
                "project fingerprint does not match the persisted launch basis"
            )
        _require_text("actor_id", actor_id, max_length=128)
        _require_text("command_id", command_id, max_length=128)
        launched_at = timestamp or datetime.now(timezone.utc)
        launch_fingerprint = self._launch_fingerprint(
            actor_id=actor_id,
            command_id=command_id,
        )
        return replace(
            self,
            status=ProjectStatus.LAUNCH_REQUESTED,
            launched_by=actor_id,
            launched_at=launched_at,
            launch_request_fingerprint=launch_fingerprint,
            launch_command_id=command_id,
            updated_at=launched_at,
            revision=self.revision + 1,
        )


def fingerprint_event_payload(payload: Mapping[str, Any]) -> str:
    """Fingerprint one public event envelope without mutating stored history."""
    return _sha256(_normalize_json(dict(payload), path="event"))
