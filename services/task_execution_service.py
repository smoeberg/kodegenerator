"""P3-14 canonical task execution boundary.

The service is deliberately provider-agnostic. It accepts a deterministic
executor factory and never embeds LLM/provider behavior in the authority or
execution contract.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol
from datetime import datetime, timezone

from domain.authorization_audit import create_authorization_audit_event
from domain.authority import AuthorizationDecision
from domain.event import Event, EventType
from domain.principal import Principal
from domain.task_execution import (
    ExecutionResult,
    TaskExecutionReceipt,
    TaskExecutionRequest,
    TaskExecutionStatus,
)
from infrastructure.persistence.uow import UnitOfWork
from services.authorization_service import AuthorizationService


class TaskExecutor(Protocol):
    """Minimal execution adapter; providers remain outside P3-14."""

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class TaskExecutorFactory(Protocol):
    """Resolve exactly one executor for a canonical task type."""

    def get(self, task_type: str) -> TaskExecutor: ...


class UnknownTaskTypeError(LookupError):
    """Raised when a task type has no registered executor."""


class ExecutionConflictError(RuntimeError):
    """Raised when an execution ID is reused with different request data."""


class RuntimeNotReadyError(RuntimeError):
    """Raised when execution is attempted before runtime readiness."""


@dataclass(frozen=True)
class DictTaskExecutorFactory:
    """Deterministic explicit task-type registry."""

    executors: dict[str, TaskExecutor]

    def get(self, task_type: str) -> TaskExecutor:
        executor = self.executors.get(task_type)
        if executor is None:
            raise UnknownTaskTypeError(f"No executor registered for task type: {task_type}")
        return executor


class TaskExecutionService:
    """Single fail-closed boundary from authorized request to execution."""

    def __init__(self, uow: UnitOfWork, executor_factory: TaskExecutorFactory, *, runtime_ready: bool) -> None:
        self.uow = uow
        self.executor_factory = executor_factory
        self.runtime_ready = runtime_ready

    def execute(
        self,
        principal: Principal,
        request: TaskExecutionRequest,
    ) -> ExecutionResult:
        if not self.runtime_ready:
            raise RuntimeNotReadyError("DOR runtime has not been booted")

        decision = AuthorizationService(self.uow).authorize(
            principal=principal,
            actor_id=request.actor_id,
            organization_id=request.organization_id,
            capability_id=request.capability_id,
            resource_id=request.resource_id,
            resource_organization_id=request.resource_organization_id,
        )
        self._record_authorization(decision, request)
        if not decision.allowed:
            raise PermissionError(f"Task execution denied: {decision.reason_code}")

        existing = self.uow.task_executions.get(request.execution_id, request.organization_id)
        if existing is not None:
            self._assert_same_request(existing, request)
            if existing.status in {
                TaskExecutionStatus.RUNNING,
                TaskExecutionStatus.SUCCEEDED,
                TaskExecutionStatus.FAILED,
                TaskExecutionStatus.CANCELLED,
            }:
                return ExecutionResult(
                    execution_id=existing.execution_id,
                    status=existing.status,
                    result=existing.result,
                    error_code=existing.error_code,
                    error_message=existing.error_message,
                )
        else:
            existing = TaskExecutionReceipt(
                execution_id=request.execution_id,
                organization_id=request.organization_id,
                actor_id=request.actor_id,
                task_type=request.task_type,
                capability_id=request.capability_id,
                payload=dict(request.payload),
                resource_id=request.resource_id,
                resource_organization_id=request.resource_organization_id,
            )
            self.uow.task_executions.add(existing)

        existing.transition(TaskExecutionStatus.RUNNING)
        self.uow.task_executions.update(existing)
        self._append_execution_event(EventType.EXECUTION_STARTED, existing)
        self.uow.session.commit()

        try:
            executor = self.executor_factory.get(request.task_type)
            result = executor.execute(dict(request.payload))
            if not isinstance(result, dict):
                raise TypeError("Task executor result must be a dictionary")
        except UnknownTaskTypeError:
            self._finish_failed(existing, "executor_not_registered")
            raise
        except Exception:
            # Do not persist arbitrary exception text: it may contain secrets.
            self._finish_failed(existing, "execution_failed")
            return ExecutionResult(
                execution_id=existing.execution_id,
                status=TaskExecutionStatus.FAILED,
                error_code="execution_failed",
                error_message="Task executor failed",
            )

        existing.mark_succeeded(result)
        self.uow.task_executions.update(existing)
        self._append_execution_event(EventType.EXECUTION_COMPLETED, existing)
        self.uow.session.commit()
        return ExecutionResult(
            execution_id=existing.execution_id,
            status=existing.status,
            result=existing.result,
        )

    def _finish_failed(self, receipt: TaskExecutionReceipt, error_code: str) -> None:
        receipt.mark_failed(error_code, "Task execution failed")
        self.uow.task_executions.update(receipt)
        self._append_execution_event(EventType.EXECUTION_FAILED, receipt)
        self.uow.session.commit()

    def _record_authorization(self, decision: AuthorizationDecision, request: TaskExecutionRequest) -> None:
        self.uow.events.append(
            create_authorization_audit_event(
                decision,
                command_id=request.execution_id,
                command_type=request.task_type,
                allowed=decision.allowed,
            )
        )
        self.uow.session.commit()

    def _append_execution_event(self, event_type: EventType, receipt: TaskExecutionReceipt) -> None:
        self.uow.events.append(
            Event(
                event_type=event_type,
                aggregate_id=receipt.execution_id,
                aggregate_type="task_execution",
                organization_id=receipt.organization_id,
                actor_id=receipt.actor_id,
                timestamp=datetime.now(timezone.utc),
                correlation_id=receipt.execution_id,
                metadata={
                    "execution_id": receipt.execution_id,
                    "task_type": receipt.task_type,
                    "status": receipt.status.value,
                    "error_code": receipt.error_code,
                },
            )
        )

    @staticmethod
    def _assert_same_request(receipt: TaskExecutionReceipt, request: TaskExecutionRequest) -> None:
        same = (
            receipt.organization_id == request.organization_id
            and receipt.actor_id == request.actor_id
            and receipt.task_type == request.task_type
            and receipt.capability_id == request.capability_id
            and receipt.payload == request.payload
            and receipt.resource_id == request.resource_id
            and receipt.resource_organization_id == request.resource_organization_id
        )
        if not same:
            raise ExecutionConflictError(
                f"Execution ID already used with different request data: {request.execution_id}"
            )
