"""Adapter that connects Phase 7 workers to the existing governed execution service."""
from __future__ import annotations

from typing import Any, Protocol

from domain.task_execution import TaskExecutionRequest
from infrastructure.runtime.execution import ExecutionResult


class GovernedExecutor(Protocol):
    def execute(self, request: TaskExecutionRequest) -> Any: ...


class GovernedExecutionHandler:
    """Translate queue payloads into the canonical P3-14 request boundary.

    Authorization, verification and application-specific execution remain in
    the existing service; this adapter deliberately does not duplicate them.
    """

    def __init__(self, executor: GovernedExecutor):
        self.executor = executor

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = TaskExecutionRequest(
            execution_id=str(payload["execution_id"]),
            organization_id=str(payload["organization_id"]),
            actor_id=str(payload["actor_id"]),
            task_type=str(payload["task_type"]),
            capability_id=str(payload["capability_id"]),
            payload=dict(payload.get("payload", {})),
            resource_id=payload.get("resource_id"),
            resource_organization_id=payload.get("resource_organization_id"),
        )
        result = self.executor.execute(request)
        if isinstance(result, dict):
            return result
        return {"result": result}
