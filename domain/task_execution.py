"""P3-14 canonical task execution domain contract."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class TaskExecutionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL = frozenset({TaskExecutionStatus.SUCCEEDED, TaskExecutionStatus.FAILED, TaskExecutionStatus.CANCELLED})
_ALLOWED_TRANSITIONS = {
    TaskExecutionStatus.PENDING: frozenset({TaskExecutionStatus.RUNNING, TaskExecutionStatus.CANCELLED}),
    TaskExecutionStatus.RUNNING: frozenset({TaskExecutionStatus.SUCCEEDED, TaskExecutionStatus.FAILED, TaskExecutionStatus.CANCELLED}),
    TaskExecutionStatus.SUCCEEDED: frozenset(),
    TaskExecutionStatus.FAILED: frozenset(),
    TaskExecutionStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class TaskExecutionRequest:
    """Immutable request crossing the canonical execution boundary."""

    execution_id: str
    organization_id: str
    actor_id: str
    task_type: str
    capability_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    resource_id: str | None = None
    resource_organization_id: str | None = None

    def __post_init__(self) -> None:
        required = {
            "execution_id": self.execution_id,
            "organization_id": self.organization_id,
            "actor_id": self.actor_id,
            "task_type": self.task_type,
            "capability_id": self.capability_id,
        }
        if any(not value or value.strip() != value for value in required.values()):
            raise ValueError("TaskExecutionRequest requires non-empty canonical identifiers")
        if self.resource_id is not None and self.resource_organization_id is None:
            raise ValueError("resource_organization_id is required when resource_id is set")


@dataclass
class TaskExecutionReceipt:
    """Durable execution state and result metadata."""

    execution_id: str
    organization_id: str
    actor_id: str
    task_type: str
    capability_id: str
    payload: dict[str, Any]
    status: TaskExecutionStatus = TaskExecutionStatus.PENDING
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    resource_id: str | None = None
    resource_organization_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, target: TaskExecutionStatus) -> None:
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            raise ValueError(f"Invalid task execution transition: {self.status} -> {target}")
        self.status = target
        self.updated_at = datetime.now(timezone.utc)

    @property
    def terminal(self) -> bool:
        return self.status in _TERMINAL

    def mark_succeeded(self, result: dict[str, Any] | None = None) -> None:
        self.transition(TaskExecutionStatus.SUCCEEDED)
        self.result = result or {}
        self.error_code = None
        self.error_message = None

    def mark_failed(self, error_code: str, error_message: str) -> None:
        if not error_code or not error_message:
            raise ValueError("Failed execution requires an error code and message")
        self.transition(TaskExecutionStatus.FAILED)
        self.error_code = error_code
        self.error_message = error_message
        self.result = None

    def mark_cancelled(self) -> None:
        self.transition(TaskExecutionStatus.CANCELLED)


@dataclass(frozen=True)
class ExecutionResult:
    """Stable service result returned to callers."""

    execution_id: str
    status: TaskExecutionStatus
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
