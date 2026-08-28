"""Pipeline integration layer (Opgave 2).

Bridges the pipeline orchestrator, the canonical TaskExecutionService and
the DORRuntime so a pipeline can be started and driven end-to-end from the
API without leaking orchestration details into request handlers.

Wire-up contract:
    integration = PipelineIntegration(runtime, task_execution_service, factory)
    workflow_id = integration.start_pipeline(requirements_yaml, org_id, creator)
    integration.advance(workflow_id)
    integration.complete_task(task, result)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from domain.task import Task
from domain.task_execution import TaskExecutionRequest
from domain.principal import Principal
from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from services.task_execution_service import TaskExecutionService

logger = logging.getLogger(__name__)


class PipelineIntegration:
    """Facade used by API endpoints to drive pipelines."""

    def __init__(
        self,
        runtime: DORRuntime,
        orchestrator: Optional[PipelineOrchestrator] = None,
        task_execution_service: Optional[TaskExecutionService] = None,
    ) -> None:
        self._runtime = runtime
        self._orchestrator = orchestrator or PipelineOrchestrator(runtime)
        self._task_execution_service = task_execution_service

    # ------------------------------------------------------------------ #
    @property
    def orchestrator(self) -> PipelineOrchestrator:
        return self._orchestrator

    def start_pipeline(self, requirements_yaml: str, organization_id: str, created_by: str) -> str:
        return self._orchestrator.start_pipeline(requirements_yaml, organization_id, created_by)

    def advance(self, workflow_id: str) -> None:
        self._orchestrator.advance_pipeline(workflow_id)

    def complete_task(self, task: Task, result: Optional[Dict[str, Any]] = None) -> None:
        if result is not None:
            task.result = result
        self._orchestrator.handle_task_completion(task)

    def status(self, workflow_id: str) -> Dict[str, Any]:
        return self._orchestrator.get_pipeline_status(workflow_id)

    def approve_gate(self, workflow_id: str, gate_id: str, approver: str, decision: str = "approved") -> bool:
        return self._orchestrator.approve_gate(workflow_id, gate_id, approver, decision)

    # ------------------------------------------------------------------ #
    # Canonical TaskExecutionService bridge
    # ------------------------------------------------------------------ #
    def execute_pipeline_task(
        self,
        principal: Principal,
        workflow_id: str,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run a pipeline task through the canonical P3-14 service (if wired)."""
        if self._task_execution_service is None:
            raise RuntimeError("TaskExecutionService not wired into PipelineIntegration")
        request = TaskExecutionRequest(
            execution_id=f"pipeline-{workflow_id}-{task_type}",
            organization_id=principal.organization_id,
            actor_id=principal.actor_id,
            task_type=task_type,
            capability_id=f"pipeline.{task_type}",
            payload=payload or {},
        )
        result = self._task_execution_service.execute(principal, request)
        return {"execution_id": result.execution_id, "status": result.status}
