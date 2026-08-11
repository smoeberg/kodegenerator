"""Phase 7 adapter from durable worker messages to the governed P3-14 service."""
from __future__ import annotations

from typing import Any, Callable, Protocol

from domain.principal import Principal
from domain.task_execution import ExecutionResult, TaskExecutionRequest


class GovernedExecutionService(Protocol):
    def execute(self, principal: Principal, request: TaskExecutionRequest) -> ExecutionResult: ...


class GovernedExecutionHandler:
    """Execute one queue payload through the canonical authorization boundary.

    A worker never executes provider logic directly. It reconstructs the
    canonical request, creates a principal bound to the requested actor, and
    delegates to TaskExecutionService, which re-checks persisted membership,
    actor status and capability authority.
    """

    def __init__(self, service_factory: Callable[[], GovernedExecutionService]):
        self.service_factory = service_factory

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

        # The actor identity is intentionally bound to the canonical request.
        # AuthorizationService still verifies the actor against persisted
        # organization membership, active status, and effective capabilities.
        principal = Principal(id=request.actor_id, type="service")
        result = self.service_factory().execute(principal, request)

        return {
            "execution_id": result.execution_id,
            "status": result.status.value,
            "result": result.result,
            "error_code": result.error_code,
            "error_message": result.error_message,
        }
