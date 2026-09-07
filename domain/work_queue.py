"""Minimal DOR Work Queue v0 domain contracts.

This module contains domain representations only. It intentionally does not
implement persistence, scheduling, claiming, locking, review orchestration, or
worker dispatch.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Optional
from uuid import uuid4

from .capability import Capability


class WorkUnitContractError(ValueError):
    """Raised when a Work Queue domain contract cannot be represented."""


class WorkUnitState(Enum):
    """Lifecycle states defined by Work Queue v0."""

    PENDING = auto()
    READY = auto()
    CLAIMED = auto()
    AWAITING_REVIEW = auto()
    REJECTED = auto()
    APPROVED = auto()
    FAILED = auto()


@dataclass(frozen=True)
class ImmutableVersionRef:
    """Domain-agnostic reference to one exact immutable version.

    ``kind`` identifies the versioning system without constraining this domain
    to one such system. Examples include ``git_commit``, ``document_revision``,
    ``dataset_snapshot`` and ``contract_version``; no taxonomy is enforced here.
    """

    kind: str
    value: str

    def __post_init__(self) -> None:
        _require_canonical_text(self.kind, "kind")
        _require_canonical_text(self.value, "value")


@dataclass(frozen=True)
class DependencyVersionBinding:
    """Bind one upstream WorkUnit ID to the exact immutable version consumed."""

    work_unit_id: str
    version: ImmutableVersionRef

    def __post_init__(self) -> None:
        _require_canonical_text(self.work_unit_id, "work_unit_id")
        if not isinstance(self.version, ImmutableVersionRef):
            raise WorkUnitContractError("version must be an ImmutableVersionRef")


@dataclass(frozen=True)
class WorkerLease:
    """Value object carrying lease information without implementing lease logic."""

    lease_id: str
    worker_id: str
    claimed_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        _require_canonical_text(self.lease_id, "lease_id")
        _require_canonical_text(self.worker_id, "worker_id")
        claimed_at = _require_utc_datetime(self.claimed_at, "claimed_at")
        expires_at = _require_utc_datetime(self.expires_at, "expires_at")
        if expires_at <= claimed_at:
            raise WorkUnitContractError("expires_at must be after claimed_at")
        object.__setattr__(self, "claimed_at", claimed_at)
        object.__setattr__(self, "expires_at", expires_at)


@dataclass
class WorkUnit:
    """Minimal Work Queue v0 work item.

    The model describes work and its immutable dependency/version bindings. It
    does not decide when work is ready, claim work, acquire locks, dispatch
    workers, or perform review transitions.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    required_capability: Capability = field(kw_only=True)
    state: WorkUnitState = WorkUnitState.PENDING
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    depends_on_snapshot: tuple[DependencyVersionBinding, ...] = field(default_factory=tuple)
    base_version: Optional[ImmutableVersionRef] = None
    allowed_resources: tuple[str, ...] = field(default_factory=tuple)
    acceptance_refs: tuple[str, ...] = field(default_factory=tuple)
    delivered_artifact_version: Optional[ImmutableVersionRef] = None
    claimed_by: Optional[str] = None
    lease: Optional[WorkerLease] = None
    previous_worker: Optional[str] = None
    rework_attempts: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        _require_canonical_text(self.id, "id")
        _require_canonical_text(self.title, "title")
        if not isinstance(self.state, WorkUnitState):
            raise WorkUnitContractError("state must be a WorkUnitState")
        if not isinstance(self.required_capability, Capability):
            raise WorkUnitContractError("required_capability must be a DOR Capability")
        if type(self.rework_attempts) is not int or self.rework_attempts < 0:
            raise WorkUnitContractError("rework_attempts must be a non-negative integer")
        self.created_at = _require_utc_datetime(self.created_at, "created_at")
        self.updated_at = _require_utc_datetime(self.updated_at, "updated_at")
        if self.updated_at < self.created_at:
            raise WorkUnitContractError("updated_at must not precede created_at")

        self.depends_on = _canonical_text_tuple(self.depends_on, "depends_on")
        self.depends_on_snapshot = _binding_tuple(self.depends_on_snapshot)
        self.allowed_resources = _canonical_text_tuple(self.allowed_resources, "allowed_resources")
        self.acceptance_refs = _canonical_text_tuple(self.acceptance_refs, "acceptance_refs")

        if self.base_version is not None and not isinstance(self.base_version, ImmutableVersionRef):
            raise WorkUnitContractError("base_version must be an ImmutableVersionRef")
        if self.delivered_artifact_version is not None and not isinstance(
            self.delivered_artifact_version, ImmutableVersionRef
        ):
            raise WorkUnitContractError("delivered_artifact_version must be an ImmutableVersionRef")
        if self.claimed_by is not None:
            _require_canonical_text(self.claimed_by, "claimed_by")
        if self.previous_worker is not None:
            _require_canonical_text(self.previous_worker, "previous_worker")
        if self.lease is not None and not isinstance(self.lease, WorkerLease):
            raise WorkUnitContractError("lease must be a WorkerLease")


def _require_canonical_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise WorkUnitContractError(f"{field_name} must be non-empty canonical text")
    return value


def _canonical_text_tuple(values: object, field_name: str) -> tuple[str, ...]:
    if not isinstance(values, (tuple, list)):
        raise WorkUnitContractError(f"{field_name} must contain text values")
    result = tuple(_require_canonical_text(value, field_name) for value in values)
    if len(result) != len(set(result)):
        raise WorkUnitContractError(f"{field_name} must not contain duplicates")
    return result


def _binding_tuple(values: object) -> tuple[DependencyVersionBinding, ...]:
    if not isinstance(values, (tuple, list)):
        raise WorkUnitContractError("depends_on_snapshot must contain dependency bindings")
    result = tuple(values)
    if any(not isinstance(value, DependencyVersionBinding) for value in result):
        raise WorkUnitContractError("depends_on_snapshot must contain DependencyVersionBinding values")
    work_unit_ids = [value.work_unit_id for value in result]
    if len(work_unit_ids) != len(set(work_unit_ids)):
        raise WorkUnitContractError("depends_on_snapshot must contain one binding per WorkUnit ID")
    return result


def _require_utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise WorkUnitContractError(f"{field_name} must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise WorkUnitContractError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "DependencyVersionBinding",
    "ImmutableVersionRef",
    "WorkUnit",
    "WorkUnitContractError",
    "WorkUnitState",
    "WorkerLease",
]
