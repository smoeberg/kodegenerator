"""Governed project aggregate for the first-party Control Plane."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field, replace
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
    ACTIVE = "active"
    COMPLETION_PENDING = "completion_pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ARCHIVED = "archived"


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


def _require_sha256(name: str, value: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ProjectContractError(f"{name} must be lowercase SHA-256")
    return value


def _require_digest_tuple(name: str, values: tuple[str, ...]) -> tuple[str, ...]:
    canonical = tuple(sorted(values))
    if not canonical or canonical != values or len(set(canonical)) != len(canonical):
        raise ProjectContractError(f"{name} must contain unique sorted SHA-256 values")
    for value in canonical:
        _require_sha256(name, value)
    return canonical


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
class ProjectCompletionRecord:
    """Immutable content-addressed proof for one exact project completion."""

    organization_id: str
    project_id: str
    final_project_revision: int
    onboarding_intent_id: str
    plan_request_fingerprint: str
    repository_commit_sha: str
    delivery_certificate_ids: tuple[str, ...]
    traceability_manifest_ids: tuple[str, ...]
    integration_evidence_ids: tuple[str, ...]
    completed_by: str
    completed_at: datetime
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        _require_text("organization_id", self.organization_id, max_length=128)
        _require_text("project_id", self.project_id, max_length=128)
        if type(self.final_project_revision) is not int or self.final_project_revision < 0:
            raise ProjectContractError("final_project_revision must be non-negative")
        _require_text("onboarding_intent_id", self.onboarding_intent_id, max_length=128)
        _require_sha256("plan_request_fingerprint", self.plan_request_fingerprint)
        _require_sha256("repository_commit_sha", self.repository_commit_sha)
        object.__setattr__(
            self,
            "delivery_certificate_ids",
            _require_digest_tuple("delivery_certificate_ids", self.delivery_certificate_ids),
        )
        object.__setattr__(
            self,
            "traceability_manifest_ids",
            _require_digest_tuple("traceability_manifest_ids", self.traceability_manifest_ids),
        )
        object.__setattr__(
            self,
            "integration_evidence_ids",
            _require_digest_tuple("integration_evidence_ids", self.integration_evidence_ids),
        )
        _require_text("completed_by", self.completed_by, max_length=128)
        if not isinstance(self.completed_at, datetime):
            raise ProjectContractError("completed_at must be a datetime")
        object.__setattr__(self, "record_id", _sha256(self.canonical_dict()))

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "contract_version": CONTROL_PLANE_CONTRACT_VERSION,
            "record_type": "ProjectCompletionRecord",
            "organization_id": self.organization_id,
            "project_id": self.project_id,
            "final_project_revision": self.final_project_revision,
            "onboarding_intent_id": self.onboarding_intent_id,
            "plan_request_fingerprint": self.plan_request_fingerprint,
            "repository_commit_sha": self.repository_commit_sha,
            "delivery_certificate_ids": list(self.delivery_certificate_ids),
            "traceability_manifest_ids": list(self.traceability_manifest_ids),
            "integration_evidence_ids": list(self.integration_evidence_ids),
            "completed_by": self.completed_by,
            "completed_at": _timestamp(self.completed_at),
        }


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
    active_plan_request_fingerprint: str | None = None
    active_scope_activated_by: str | None = None
    active_scope_activated_at: datetime | None = None
    active_scope_command_id: str | None = None
    completion_requested_by: str | None = None
    completion_requested_at: datetime | None = None
    completion_request_command_id: str | None = None
    completion_record_id: str | None = None
    completed_by: str | None = None
    completed_at: datetime | None = None
    cancelled_by: str | None = None
    cancelled_at: datetime | None = None
    cancel_command_id: str | None = None
    cancellation_reason: str | None = None
    archived_by: str | None = None
    archived_at: datetime | None = None
    archive_command_id: str | None = None
    archived_from_status: ProjectStatus | None = None
    continued_from_project_id: str | None = None
    revision: int = 0
    contract_version: str = CONTROL_PLANE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.status, ProjectStatus):
            raise ProjectContractError("project status is not canonical")
        if not isinstance(self.intent, ProjectIntent):
            raise ProjectContractError("project intent is not canonical")
        for name, value in (("created_at", self.created_at), ("updated_at", self.updated_at)):
            if not isinstance(value, datetime):
                raise ProjectContractError(f"{name} must be a datetime")
        _require_text("project id", self.id, max_length=128)
        _require_text("organization id", self.organization_id, max_length=128)
        _require_text("project name", self.name, max_length=255)
        if not isinstance(self.description, str) or len(self.description) > 20_000:
            raise ProjectContractError("project description exceeds 20000 characters")
        _require_text("created_by", self.created_by, max_length=128)
        if self.continued_from_project_id is not None:
            _require_text("continued_from_project_id", self.continued_from_project_id, max_length=128)
            if self.continued_from_project_id == self.id:
                raise ProjectContractError("project cannot continue from itself")
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
        scope_fields = (
            self.active_plan_request_fingerprint,
            self.active_scope_activated_by,
            self.active_scope_activated_at,
            self.active_scope_command_id,
        )
        completion_request_fields = (
            self.completion_requested_by,
            self.completion_requested_at,
            self.completion_request_command_id,
        )
        completed_fields = (
            self.completion_record_id,
            self.completed_by,
            self.completed_at,
        )
        cancelled_fields = (
            self.cancelled_by,
            self.cancelled_at,
            self.cancel_command_id,
            self.cancellation_reason,
        )
        archive_fields = (
            self.archived_by,
            self.archived_at,
            self.archive_command_id,
            self.archived_from_status,
        )

        if self.status is ProjectStatus.CREATED:
            if any(launch_fields) or any(scope_fields) or any(completion_request_fields) or any(completed_fields) or any(cancelled_fields) or any(archive_fields):
                raise ProjectContractError("created projects cannot contain lifecycle transition metadata")
            if self.revision != 0:
                raise ProjectContractError("created projects must have revision zero")
            return

        if any(item is None for item in launch_fields):
            raise ProjectContractError("launched projects require complete launch metadata")
        if not isinstance(self.launched_at, datetime):
            raise ProjectContractError("launched_at must be a datetime")
        _require_text("launched_by", self.launched_by or "", max_length=128)
        _require_sha256("launch_request_fingerprint", self.launch_request_fingerprint or "")
        _require_text("launch_command_id", self.launch_command_id or "", max_length=128)
        expected = self._launch_fingerprint(actor_id=self.launched_by or "", command_id=self.launch_command_id or "")
        if self.launch_request_fingerprint != expected:
            raise ProjectContractError("launch request fingerprint does not match project provenance")

        if self.status is ProjectStatus.LAUNCH_REQUESTED:
            if any(scope_fields) or any(completion_request_fields) or any(completed_fields) or any(cancelled_fields) or any(archive_fields):
                raise ProjectContractError("launch-requested projects contain invalid lifecycle metadata")
            if self.revision != 1:
                raise ProjectContractError("launch-requested projects must have revision one")
            return

        if any(item is None for item in scope_fields):
            raise ProjectContractError("post-activation projects require complete active-scope metadata")
        _require_sha256("active_plan_request_fingerprint", self.active_plan_request_fingerprint or "")
        _require_text("active_scope_activated_by", self.active_scope_activated_by or "", max_length=128)
        _require_text("active_scope_command_id", self.active_scope_command_id or "", max_length=128)
        if not isinstance(self.active_scope_activated_at, datetime):
            raise ProjectContractError("active_scope_activated_at must be a datetime")

        if self.status is ProjectStatus.ACTIVE:
            if any(completion_request_fields) or any(completed_fields) or any(cancelled_fields) or any(archive_fields):
                raise ProjectContractError("active projects contain invalid terminal metadata")
            if self.revision < 2:
                raise ProjectContractError("active projects require revision two or greater")
            return

        if self.status is ProjectStatus.COMPLETION_PENDING:
            if any(item is None for item in completion_request_fields):
                raise ProjectContractError("completion-pending projects require request provenance")
            if any(completed_fields) or any(cancelled_fields) or any(archive_fields):
                raise ProjectContractError("completion-pending projects contain terminal metadata")
            self._validate_completion_request()
            return

        if self.status is ProjectStatus.COMPLETED:
            if any(item is None for item in completion_request_fields) or any(item is None for item in completed_fields):
                raise ProjectContractError("completed projects require completion provenance")
            if any(cancelled_fields) or any(archive_fields):
                raise ProjectContractError("completed projects contain invalid terminal metadata")
            self._validate_completion_request()
            self._validate_completed()
            return

        if self.status is ProjectStatus.CANCELLED:
            if any(completion_request_fields) or any(completed_fields) or any(archive_fields):
                raise ProjectContractError("cancelled projects contain invalid completion/archive metadata")
            if any(item is None for item in cancelled_fields):
                raise ProjectContractError("cancelled projects require complete cancellation provenance")
            self._validate_cancelled()
            return

        if self.status is ProjectStatus.ARCHIVED:
            if any(item is None for item in archive_fields):
                raise ProjectContractError("archived projects require complete archive provenance")
            _require_text("archived_by", self.archived_by or "", max_length=128)
            _require_text("archive_command_id", self.archive_command_id or "", max_length=128)
            if not isinstance(self.archived_at, datetime):
                raise ProjectContractError("archived_at must be a datetime")
            if self.archived_from_status is ProjectStatus.COMPLETED:
                if any(item is None for item in completion_request_fields) or any(item is None for item in completed_fields) or any(cancelled_fields):
                    raise ProjectContractError("archived completed project provenance is incomplete")
                self._validate_completion_request()
                self._validate_completed()
            elif self.archived_from_status is ProjectStatus.CANCELLED:
                if any(completion_request_fields) or any(completed_fields) or any(item is None for item in cancelled_fields):
                    raise ProjectContractError("archived cancelled project provenance is incomplete")
                self._validate_cancelled()
            else:
                raise ProjectContractError("archive must preserve completed or cancelled terminal truth")

    def _validate_completion_request(self) -> None:
        _require_text("completion_requested_by", self.completion_requested_by or "", max_length=128)
        _require_text("completion_request_command_id", self.completion_request_command_id or "", max_length=128)
        if not isinstance(self.completion_requested_at, datetime):
            raise ProjectContractError("completion_requested_at must be a datetime")

    def _validate_completed(self) -> None:
        _require_sha256("completion_record_id", self.completion_record_id or "")
        _require_text("completed_by", self.completed_by or "", max_length=128)
        if not isinstance(self.completed_at, datetime):
            raise ProjectContractError("completed_at must be a datetime")

    def _validate_cancelled(self) -> None:
        _require_text("cancelled_by", self.cancelled_by or "", max_length=128)
        _require_text("cancel_command_id", self.cancel_command_id or "", max_length=128)
        _require_text("cancellation_reason", self.cancellation_reason or "", max_length=2_000)
        if not isinstance(self.cancelled_at, datetime):
            raise ProjectContractError("cancelled_at must be a datetime")

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
        continued_from_project_id: str | None = None,
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
            continued_from_project_id=continued_from_project_id,
        )

    def immutable_dict(self) -> dict[str, Any]:
        payload = {
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
        if self.continued_from_project_id is not None:
            payload["continued_from_project_id"] = self.continued_from_project_id
        return payload

    @property
    def fingerprint(self) -> str:
        """Fingerprint immutable project content, independent of mutable status."""
        return _sha256(self.immutable_dict())

    @property
    def ordinary_work_allowed(self) -> bool:
        return self.status is ProjectStatus.ACTIVE

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

    def request_launch(self, *, actor_id: str, command_id: str, expected_project_fingerprint: str, timestamp: datetime | None = None) -> "Project":
        if self.status is not ProjectStatus.CREATED:
            raise ProjectStateError("project is not in the created state")
        if expected_project_fingerprint != self.fingerprint:
            raise ProjectFingerprintError("project fingerprint does not match the persisted launch basis")
        _require_text("actor_id", actor_id, max_length=128)
        _require_text("command_id", command_id, max_length=128)
        launched_at = timestamp or datetime.now(timezone.utc)
        return replace(
            self,
            status=ProjectStatus.LAUNCH_REQUESTED,
            launched_by=actor_id,
            launched_at=launched_at,
            launch_request_fingerprint=self._launch_fingerprint(actor_id=actor_id, command_id=command_id),
            launch_command_id=command_id,
            updated_at=launched_at,
            revision=self.revision + 1,
        )

    def activate_scope(self, *, actor_id: str, command_id: str, plan_request_fingerprint: str, expected_revision: int, timestamp: datetime | None = None) -> "Project":
        """Atomically replace the exact active plan identity at one project revision."""
        if self.status not in {ProjectStatus.LAUNCH_REQUESTED, ProjectStatus.ACTIVE}:
            raise ProjectStateError("project cannot activate scope in its current state")
        if expected_revision != self.revision:
            raise ProjectStateError("project revision conflict")
        _require_text("actor_id", actor_id, max_length=128)
        _require_text("command_id", command_id, max_length=128)
        _require_sha256("plan_request_fingerprint", plan_request_fingerprint)
        activated_at = timestamp or datetime.now(timezone.utc)
        return replace(
            self,
            status=ProjectStatus.ACTIVE,
            active_plan_request_fingerprint=plan_request_fingerprint,
            active_scope_activated_by=actor_id,
            active_scope_activated_at=activated_at,
            active_scope_command_id=command_id,
            updated_at=activated_at,
            revision=self.revision + 1,
        )

    def request_completion(self, *, actor_id: str, command_id: str, expected_revision: int, expected_plan_request_fingerprint: str, timestamp: datetime | None = None) -> "Project":
        """Freeze ordinary work while exact server-owned completion evidence is verified."""
        if self.status is not ProjectStatus.ACTIVE:
            raise ProjectStateError("only an active project can request completion")
        if expected_revision != self.revision:
            raise ProjectStateError("project revision conflict")
        _require_sha256("expected_plan_request_fingerprint", expected_plan_request_fingerprint)
        if self.active_plan_request_fingerprint != expected_plan_request_fingerprint:
            raise ProjectFingerprintError("active plan fingerprint changed before completion request")
        _require_text("actor_id", actor_id, max_length=128)
        _require_text("command_id", command_id, max_length=128)
        requested_at = timestamp or datetime.now(timezone.utc)
        return replace(
            self,
            status=ProjectStatus.COMPLETION_PENDING,
            completion_requested_by=actor_id,
            completion_requested_at=requested_at,
            completion_request_command_id=command_id,
            updated_at=requested_at,
            revision=self.revision + 1,
        )

    def complete(self, *, record: ProjectCompletionRecord, expected_revision: int) -> "Project":
        """Bind one immutable exact proof and make the project permanently completed."""
        if self.status is not ProjectStatus.COMPLETION_PENDING:
            raise ProjectStateError("project is not awaiting completion verification")
        if expected_revision != self.revision:
            raise ProjectStateError("project revision conflict")
        if record.organization_id != self.organization_id or record.project_id != self.id:
            raise ProjectFingerprintError("completion record project binding mismatch")
        if record.final_project_revision != self.revision:
            raise ProjectFingerprintError("completion record revision binding mismatch")
        if record.plan_request_fingerprint != self.active_plan_request_fingerprint:
            raise ProjectFingerprintError("completion record plan binding mismatch")
        return replace(
            self,
            status=ProjectStatus.COMPLETED,
            completion_record_id=record.record_id,
            completed_by=record.completed_by,
            completed_at=record.completed_at,
            updated_at=record.completed_at,
            revision=self.revision + 1,
        )

    def cancel(self, *, actor_id: str, command_id: str, reason: str, expected_revision: int, timestamp: datetime | None = None) -> "Project":
        """Terminate active governed work without manufacturing completion truth."""
        if self.status not in {ProjectStatus.ACTIVE, ProjectStatus.COMPLETION_PENDING}:
            raise ProjectStateError("project cannot be cancelled in its current state")
        if expected_revision != self.revision:
            raise ProjectStateError("project revision conflict")
        _require_text("actor_id", actor_id, max_length=128)
        _require_text("command_id", command_id, max_length=128)
        _require_text("reason", reason, max_length=2_000)
        cancelled_at = timestamp or datetime.now(timezone.utc)
        return replace(
            self,
            status=ProjectStatus.CANCELLED,
            completion_requested_by=None,
            completion_requested_at=None,
            completion_request_command_id=None,
            cancelled_by=actor_id,
            cancelled_at=cancelled_at,
            cancel_command_id=command_id,
            cancellation_reason=reason,
            updated_at=cancelled_at,
            revision=self.revision + 1,
        )

    def archive(self, *, actor_id: str, command_id: str, expected_revision: int, timestamp: datetime | None = None) -> "Project":
        """Archive a terminal project without deleting or rewriting provenance."""
        if self.status not in {ProjectStatus.COMPLETED, ProjectStatus.CANCELLED}:
            raise ProjectStateError("only completed or cancelled projects may be archived")
        if expected_revision != self.revision:
            raise ProjectStateError("project revision conflict")
        _require_text("actor_id", actor_id, max_length=128)
        _require_text("command_id", command_id, max_length=128)
        archived_at = timestamp or datetime.now(timezone.utc)
        return replace(
            self,
            status=ProjectStatus.ARCHIVED,
            archived_by=actor_id,
            archived_at=archived_at,
            archive_command_id=command_id,
            archived_from_status=self.status,
            updated_at=archived_at,
            revision=self.revision + 1,
        )


def fingerprint_event_payload(payload: Mapping[str, Any]) -> str:
    """Fingerprint one public event envelope without mutating stored history."""
    return _sha256(_normalize_json(dict(payload), path="event"))
