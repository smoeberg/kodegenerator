"""Process-local shared pipeline orchestrator + swarm task queue.

API handlers and worker processes in the same OS process must see the same
pipeline tasks. The previous API pattern (`PipelineOrchestrator(runtime)` per
request) made claiming impossible because tasks lived in a throw-away registry.

Usage::

    registry = get_pipeline_registry(runtime)
    workflow_id = registry.orchestrator.start_pipeline(...)
    registry.orchestrator.advance_pipeline(workflow_id)  # enqueues tasks
    queued = registry.queue.claim_next_task(worker_id, capabilities)
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from runtime.pipeline_orchestrator import PipelineOrchestrator

from domain.task import TaskStatus
from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_state_store import PipelineStateStore
from services.database_swarm_queue import DatabaseSwarmTaskQueue
from services.swarm_persistence import SQLiteTaskQueue
from services.swarm_task_queue import QueuedTaskStatus, SwarmTaskQueue

_lock = threading.RLock()
_registries: dict[str, "PipelineRegistry"] = {}


class PipelineAwareQueue:
    """SwarmTaskQueue decorator: complete/fail also update domain pipeline state.

    Workers keep using claim_next_task / heartbeat / complete_task unchanged.
    On complete, the orchestrator advances the pipeline (handle_task_completion).
    """

    def __init__(
        self, queue: SwarmTaskQueue, orchestrator: PipelineOrchestrator
    ) -> None:
        self._queue = queue
        self._orchestrator = orchestrator

    @property
    def lease_seconds(self) -> int:
        return self._queue.lease_seconds

    def enqueue_wbs_plan(self, plan: Any) -> int:
        return self._queue.enqueue_wbs_plan(plan)

    def claim_next_task(self, agent_id: str, capabilities: list[str]):
        # API and workers are separate processes in demo/production. Refresh
        # the durable snapshot before a claim so the worker has the workflow
        # context required by the claimed database task.
        if isinstance(self._queue, DatabaseSwarmTaskQueue):
            self._orchestrator._restore()
        return self._queue.claim_next_task(agent_id, capabilities)

    def heartbeat(self, task_id: str, agent_id: str) -> None:
        self._queue.heartbeat(task_id, agent_id)

    def complete_task(self, task_id: str, agent_id: str, patch_result: Any) -> None:
        domain_task = self._orchestrator._tasks.get(task_id)
        if domain_task is not None:
            if patch_result is not None:
                domain_task.result = patch_result  # type: ignore[attr-defined]
                domain_task.metadata = {
                    **dict(domain_task.metadata or {}),
                    "execution_result": patch_result
                    if isinstance(patch_result, dict)
                    else {"value": patch_result},
                }
            # Advance the pipeline before acknowledging completion in the queue.
            self._orchestrator.handle_task_completion(domain_task)
        self._queue.complete_task(task_id, agent_id, patch_result)

    def fail_task(
        self, task_id: str, agent_id: str, error: str, retry: bool = True
    ) -> None:
        self._queue.fail_task(task_id, agent_id, error, retry=retry)
        domain_task = self._orchestrator._tasks.get(task_id)
        if domain_task is None:
            return

        # The durable queue is authoritative for whether another worker attempt
        # remains possible. Align the domain task with that decision rather than
        # duplicating retry-limit arithmetic with Task.fail().
        queued_task = self._queue.get_task(task_id)
        domain_task.retry_count = queued_task.retry_count
        domain_task.last_error = error
        domain_task.status = (
            TaskStatus.RETRYING
            if queued_task.status == QueuedTaskStatus.PENDING
            else TaskStatus.FAILED
        )
        self._orchestrator._tasks[task_id] = domain_task

        metadata = dict(domain_task.metadata or {})
        gate_id = str(metadata.get("rework_gate_id") or "")
        workflow = self._orchestrator._get_workflow(domain_task.workflow_id or "")
        if gate_id and workflow is not None:
            history = list(workflow.context.get("gate_rework_history", []) or [])
            updated: list[Any] = []
            for record in history:
                if not isinstance(record, dict) or record.get("task_id") != task_id:
                    updated.append(record)
                    continue
                replacement = dict(record)
                replacement["status"] = (
                    "retrying"
                    if domain_task.status == TaskStatus.RETRYING
                    else "failed"
                )
                replacement["error"] = error
                updated.append(replacement)
            workflow.context["gate_rework_history"] = updated

        self._orchestrator._persist()

    def pending_count(self) -> int:
        return self._queue.pending_count()

    def get_task(self, task_id: str):
        return self._queue.get_task(task_id)

    def __getattr__(self, name: str):
        return getattr(self._queue, name)


class PipelineRegistry:
    """Holds the single in-process orchestrator and the claimable task queue."""

    def __init__(
        self,
        runtime: DORRuntime,
        *,
        lease_seconds: int = 300,
        organization_id: str | None = None,
    ) -> None:
        self.runtime = runtime
        backend = os.getenv("DOR_QUEUE_BACKEND", "local").strip().lower()
        if backend == "database":
            from infrastructure.persistence.pipeline_state_store import (
                SQLAlchemyPipelineStateStore,
            )
            from infrastructure.runtime.db import build_session_factory

            database_url = os.getenv("DOR_PIPELINE_DATABASE_URL") or os.getenv(
                "DATABASE_URL"
            )
            organization_id = organization_id or os.getenv(
                "DOR_PIPELINE_STATE_ORGANIZATION_ID"
            )
            if not database_url or not organization_id:
                raise RuntimeError(
                    "database queue requires DATABASE_URL and "
                    "DOR_PIPELINE_STATE_ORGANIZATION_ID"
                )
            sessions = build_session_factory(database_url)
            self._raw_queue = DatabaseSwarmTaskQueue(
                DatabaseQueue(
                    sessions,
                    organization_id=organization_id,
                    lease_seconds=lease_seconds,
                )
            )
            state_store = SQLAlchemyPipelineStateStore(
                sessions,
                organization_id=organization_id,
                store_id=os.getenv("DOR_PIPELINE_STATE_STORE_ID", "pipeline-default"),
            )
        else:
            if os.getenv("DOR_ENV", "development").lower() in {"demo", "production"}:
                raise RuntimeError(
                    "demo and production require DOR_QUEUE_BACKEND=database"
                )
            queue_path = Path(os.getenv("DOR_PIPELINE_QUEUE_PATH", "pipeline_tasks.db"))
            state_path = Path(
                os.getenv("DOR_PIPELINE_STATE_PATH", "pipeline_state.json")
            )
            self._raw_queue = SQLiteTaskQueue(queue_path, lease_seconds=lease_seconds)
            state_store = PipelineStateStore(state_path)
        self.orchestrator = PipelineOrchestrator(
            runtime,
            task_queue=self._raw_queue,
            state_store=state_store,
        )
        # Workers see the aware queue so complete_task advances the pipeline.
        self.queue = PipelineAwareQueue(self._raw_queue, self.orchestrator)

    def reset_for_tests(self) -> None:
        """Clear workflows/tasks/queue — test only."""
        self.orchestrator._workflows.clear()
        self.orchestrator._tasks.clear()
        close = getattr(self._raw_queue, "close", None)
        if callable(close):
            close()
        self._raw_queue = SwarmTaskQueue(lease_seconds=self._raw_queue.lease_seconds)
        self.orchestrator.bind_task_queue(self._raw_queue)
        self.queue = PipelineAwareQueue(self._raw_queue, self.orchestrator)


def get_pipeline_registry(
    runtime: DORRuntime | None = None,
    *,
    lease_seconds: int = 300,
    organization_id: str | None = None,
) -> PipelineRegistry:
    """Return one process registry per authenticated organization."""
    key = organization_id or os.getenv("DOR_PIPELINE_STATE_ORGANIZATION_ID") or "local"
    with _lock:
        registry = _registries.get(key)
        if registry is None:
            if runtime is None:
                raise RuntimeError(
                    "PipelineRegistry not initialised; pass a DORRuntime on first call"
                )
            registry = PipelineRegistry(
                runtime,
                lease_seconds=lease_seconds,
                organization_id=organization_id,
            )
            _registries[key] = registry
        return registry


def reset_pipeline_registry() -> None:
    """Drop every tenant registry (tests)."""
    with _lock:
        _registries.clear()
