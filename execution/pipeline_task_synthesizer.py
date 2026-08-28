"""Bridge from swarm claim loop → canonical pipeline executors.

When a worker claims a pipeline-published ``QueuedTask``, this synthesizer:

1. Reads ``task_type`` from task metadata
2. Resolves the matching executor via ``build_pipeline_executor_registry``
3. Builds an execution payload from metadata + workflow context
4. Calls ``executor.execute(payload)`` and returns the result dict

The worker daemon stays unaware of pipeline details; it only needs a
``synthesize(task) -> dict`` callable (or object with that method).
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional, Protocol

from execution.pipeline_executors import build_pipeline_executor_registry
from services.swarm_task_queue import QueuedTask

logger = logging.getLogger(__name__)


class PipelineExecutor(Protocol):
    task_type: str

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class UnknownPipelineTaskTypeError(LookupError):
    """No executor registered for the claimed task type."""


def _default_registry() -> dict[str, PipelineExecutor]:
    return build_pipeline_executor_registry()  # type: ignore[return-value]


class PipelineTaskSynthesizer:
    """Synthesizer that runs the canonical pipeline executor for a claimed task."""

    def __init__(
        self,
        *,
        registry: Optional[Mapping[str, PipelineExecutor]] = None,
        context_provider: Optional[Callable[[str], dict[str, Any]]] = None,
    ) -> None:
        self._registry: dict[str, PipelineExecutor] = dict(
            registry if registry is not None else _default_registry()
        )
        # Optional: workflow_id → context dict (project name, requirements, …)
        self._context_provider = context_provider

    def register(self, task_type: str, executor: PipelineExecutor) -> None:
        self._registry[task_type] = executor

    def synthesize(self, task: QueuedTask) -> dict[str, Any]:
        meta = dict(task.metadata or {})
        task_type = str(meta.get("task_type") or task.name or "").strip()
        if not task_type:
            raise UnknownPipelineTaskTypeError(
                f"Queued task {task.task_id} has no task_type in metadata"
            )

        executor = self._registry.get(task_type)
        if executor is None:
            raise UnknownPipelineTaskTypeError(
                f"No pipeline executor for task_type={task_type!r} "
                f"(known: {sorted(self._registry)})"
            )

        payload = self._build_payload(task, task_type, meta)
        logger.info(
            "pipeline_synth task_id=%s task_type=%s workflow_id=%s",
            task.task_id,
            task_type,
            meta.get("workflow_id"),
        )
        result = executor.execute(payload)
        if not isinstance(result, dict):
            raise TypeError(
                f"Executor for {task_type} returned {type(result).__name__}, expected dict"
            )
        # Enrich with claim provenance for audit / downstream advance.
        result.setdefault("task_id", task.task_id)
        result.setdefault("task_type", task_type)
        if meta.get("workflow_id"):
            result.setdefault("workflow_id", meta["workflow_id"])
        return result

    def _build_payload(
        self,
        task: QueuedTask,
        task_type: str,
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        workflow_id = meta.get("workflow_id")
        context: dict[str, Any] = {}
        if workflow_id and self._context_provider is not None:
            try:
                context = dict(self._context_provider(str(workflow_id)) or {})
            except Exception:  # noqa: BLE001
                logger.exception(
                    "context_provider failed for workflow_id=%s", workflow_id
                )

        name = (
            context.get("project_name")
            or meta.get("project_name")
            or task.name
            or task_type
        )
        payload: dict[str, Any] = {
            "name": name,
            "task_id": task.task_id,
            "task_type": task_type,
            "workflow_id": workflow_id,
            "component": meta.get("component", ""),
            "requirements": context.get("requirements")
            or context.get("requirements_yaml")
            or meta.get("requirements", ""),
            "environment": context.get("environment")
            or meta.get("environment", "development"),
            "context": context,
            "metadata": meta,
        }
        # Pass through any execution_parameters embedded when the task was created.
        for key in ("execution_parameters", "payload"):
            extra = meta.get(key)
            if isinstance(extra, dict):
                payload.update(extra)
        return payload
