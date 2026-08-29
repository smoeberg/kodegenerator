"""Canonical bridge from claimed pipeline tasks to registered executors."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from services.swarm_task_queue import QueuedTask


class PipelineExecutorSynthesizer:
    """Build a current task payload and dispatch it through the executor registry.

    Queue metadata is deliberately treated as routing data, not as the source of
    truth for workflow context.  The latest context is resolved at execution time
    so every stage observes the attested output of the preceding stage.
    """

    def __init__(
        self,
        orchestrator: Any,
        executors: Mapping[str, Any],
        *,
        enrich_payload: (
            Callable[[str, dict[str, Any]], Mapping[str, Any]] | None
        ) = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._executors = dict(executors)
        self._enrich_payload = enrich_payload

    def synthesize(self, task: QueuedTask) -> dict[str, Any]:
        metadata = dict(task.metadata or {})
        task_type = str(metadata.get("task_type") or task.name)
        executor = self._executors.get(task_type)
        if executor is None:
            raise LookupError(f"no pipeline executor registered for {task_type}")

        workflow_id = str(metadata.get("workflow_id") or "")
        workflow = self._orchestrator._get_workflow(workflow_id)
        if workflow is None:
            raise ValueError(f"pipeline workflow not found: {workflow_id}")

        execution_parameters = dict(metadata.get("execution_parameters") or {})
        current_context = dict(workflow.context or {})
        payload = {
            **execution_parameters,
            **metadata,
            **current_context,
            "context": current_context,
            "task_id": task.task_id,
            "workflow_id": workflow_id,
            "organization_id": metadata.get("organization_id")
            or workflow.metadata.get("organization_id"),
            "actor_id": metadata.get("actor_id")
            or workflow.metadata.get("created_by"),
        }
        if self._enrich_payload is not None:
            payload.update(dict(self._enrich_payload(task_type, dict(payload))))
        return executor.execute(payload)
