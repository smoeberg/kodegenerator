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
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from runtime.pipeline_orchestrator import PipelineOrchestrator

from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_state_store import PipelineStateStore
from services.swarm_persistence import SQLiteTaskQueue
from services.swarm_task_queue import SwarmTaskQueue

_lock = threading.RLock()
_registry: Optional["PipelineRegistry"] = None


class PipelineAwareQueue:
    """SwarmTaskQueue decorator: complete/fail also update domain pipeline state.

    Workers keep using claim_next_task / heartbeat / complete_task unchanged.
    On complete, the orchestrator advances the pipeline (handle_task_completion).
    """

    def __init__(
        self, queue: SwarmTaskQueue, orchestrator: "PipelineOrchestrator"
    ) -> None:
        self._queue = queue
        self._orchestrator = orchestrator

    @property
    def lease_seconds(self) -> int:
        return self._queue.lease_seconds

    def enqueue_wbs_plan(self, plan: Any) -> int:
        return self._queue.enqueue_wbs_plan(plan)

    def claim_next_task(self, agent_id: str, capabilities: list[str]):
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
            # Advance pipeline state before acknowledging queue completion.
            self._orchestrator.handle_task_completion(domain_task)
        self._queue.complete_task(task_id, agent_id, patch_result)

    def fail_task(
        self, task_id: str, agent_id: str, error: str, retry: bool = True
    ) -> None:
        self._queue.fail_task(task_id, agent_id, error, retry=retry)
        domain_task = self._orchestrator._tasks.get(task_id)
        if domain_task is not None:
            domain_task.fail(error, retry=retry)

    def pending_count(self) -> int:
        return self._queue.pending_count()

    def get_task(self, task_id: str):
        return self._queue.get_task(task_id)

    def __getattr__(self, name: str):
        return getattr(self._queue, name)


class PipelineRegistry:
    """Holds the single in-process orchestrator and the claimable task queue."""

    def __init__(self, runtime: DORRuntime, *, lease_seconds: int = 300) -> None:
        self.runtime = runtime
        queue_path = Path(os.getenv("DOR_PIPELINE_QUEUE_PATH", "pipeline_tasks.db"))
        state_path = Path(os.getenv("DOR_PIPELINE_STATE_PATH", "pipeline_state.json"))
        state_store = (
            None
            if os.getenv("DOR_PIPELINE_DATABASE_URL")
            else PipelineStateStore(state_path)
        )
        self._raw_queue = SQLiteTaskQueue(queue_path, lease_seconds=lease_seconds)
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
    runtime: Optional[DORRuntime] = None,
    *,
    lease_seconds: int = 300,
) -> PipelineRegistry:
    """Return the process-wide registry, creating it on first use."""
    global _registry
    with _lock:
        if _registry is None:
            if runtime is None:
                raise RuntimeError(
                    "PipelineRegistry not initialised; pass a DORRuntime on first call"
                )
            _registry = PipelineRegistry(runtime, lease_seconds=lease_seconds)
        return _registry


def reset_pipeline_registry() -> None:
    """Drop the singleton (tests)."""
    global _registry
    with _lock:
        _registry = None
