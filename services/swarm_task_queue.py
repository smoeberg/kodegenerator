"""Thread-safe, idempotent task queue for parallel DOR swarm workers.

The queue is intentionally dependency-aware and lease based.  It keeps the
claim/heartbeat/complete transitions atomic under one lock so multiple worker
threads cannot claim the same WBS task.  A stale lease is reclaimed lazily on
queue operations, which makes crash recovery deterministic without a
background reaper.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Any, Iterable, Optional
import uuid


class QueuedTaskStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class QueuedTask:
    task_id: str
    name: str
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    priority: int = 0
    status: QueuedTaskStatus = QueuedTaskStatus.PENDING
    agent_id: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    patch_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def lease_active(self, now: datetime) -> bool:
        return self.status == QueuedTaskStatus.CLAIMED and bool(
            self.lease_expires_at and self.lease_expires_at > now
        )


class SwarmTaskQueue:
    """In-memory transactional queue suitable for a single process swarm.

    The public API is deliberately storage-agnostic so a durable SQL/Redis
    implementation can later preserve the same claim semantics.
    """

    def __init__(self, *, lease_seconds: int = 300, clock=None) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._lock = RLock()
        self._tasks: dict[str, QueuedTask] = {}
        self._plan_keys: set[str] = set()

    def enqueue_wbs_plan(self, plan: Any) -> int:
        """Enqueue a WBS plan exactly once; return number of newly queued tasks.

        Accepts the repository's WBS output convention (an object exposing
        ``tasks`` or ``wbs_tasks``) and also a plain iterable of task objects.
        """
        plan_key = self._plan_key(plan)
        tasks = self._extract_tasks(plan)
        with self._lock:
            if plan_key in self._plan_keys:
                return 0
            new_tasks = 0
            for item in tasks:
                task = self._normalise_task(item)
                if task.task_id in self._tasks:
                    continue
                self._tasks[task.task_id] = task
                new_tasks += 1
            self._plan_keys.add(plan_key)
            return new_tasks

    def claim_next_task(
        self, agent_id: str, capabilities: list[str]
    ) -> Optional[QueuedTask]:
        if not agent_id.strip():
            raise ValueError("agent_id is required")
        capability_set = set(capabilities)
        with self._lock:
            now = self._clock()
            self._reclaim_expired_locked(now)
            ready = [
                task for task in self._tasks.values()
                if task.status == QueuedTaskStatus.PENDING
                and set(task.capabilities).issubset(capability_set)
                and self._dependencies_completed_locked(task)
            ]
            if not ready:
                return None
            ready.sort(key=lambda t: (-t.priority, t.task_id))
            task = ready[0]
            task.status = QueuedTaskStatus.CLAIMED
            task.agent_id = agent_id
            task.heartbeat_at = now
            task.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            return task

    def heartbeat(self, task_id: str, agent_id: str) -> None:
        with self._lock:
            task = self._require_owned_task(task_id, agent_id)
            now = self._clock()
            if not task.lease_active(now):
                self._reclaim_expired_locked(now)
                raise RuntimeError("task lease has expired")
            task.heartbeat_at = now
            task.lease_expires_at = now + timedelta(seconds=self.lease_seconds)

    def complete_task(self, task_id: str, agent_id: str, patch_result: Any) -> None:
        with self._lock:
            task = self._require_owned_task(task_id, agent_id)
            now = self._clock()
            if not task.lease_active(now):
                self._reclaim_expired_locked(now)
                raise RuntimeError("task lease has expired")
            task.status = QueuedTaskStatus.COMPLETED
            task.patch_result = patch_result
            task.lease_expires_at = None
            task.heartbeat_at = now
            task.agent_id = None

    def fail_task(
        self, task_id: str, agent_id: str, error: str, retry: bool = True
    ) -> None:
        with self._lock:
            task = self._require_owned_task(task_id, agent_id)
            task.error = error
            task.retry_count += 1
            should_retry = retry and task.retry_count <= task.max_retries
            task.status = (
                QueuedTaskStatus.PENDING if should_retry else QueuedTaskStatus.FAILED
            )
            task.agent_id = None
            task.lease_expires_at = None
            task.heartbeat_at = self._clock()

    def pending_count(self) -> int:
        with self._lock:
            self._reclaim_expired_locked(self._clock())
            return sum(t.status == QueuedTaskStatus.PENDING for t in self._tasks.values())

    def get_task(self, task_id: str) -> QueuedTask:
        with self._lock:
            return self._tasks[task_id]

    def _reclaim_expired_locked(self, now: datetime) -> None:
        for task in self._tasks.values():
            if task.status == QueuedTaskStatus.CLAIMED and not task.lease_active(now):
                task.status = QueuedTaskStatus.PENDING
                task.agent_id = None
                task.lease_expires_at = None

    def _dependencies_completed_locked(self, task: QueuedTask) -> bool:
        return all(
            self._tasks.get(dep_id) is not None
            and self._tasks[dep_id].status == QueuedTaskStatus.COMPLETED
            for dep_id in task.dependencies
        )

    def _require_owned_task(self, task_id: str, agent_id: str) -> QueuedTask:
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        if task.status != QueuedTaskStatus.CLAIMED or task.agent_id != agent_id:
            raise PermissionError("task is not claimed by this agent")
        return task

    @staticmethod
    def _extract_tasks(plan: Any) -> list[Any]:
        if hasattr(plan, "tasks"):
            value = plan.tasks
        elif hasattr(plan, "wbs_tasks"):
            value = plan.wbs_tasks
        elif isinstance(plan, (list, tuple)):
            value = plan
        else:
            raise TypeError("WBSPlan must expose tasks or wbs_tasks")
        return list(value)

    @staticmethod
    def _plan_key(plan: Any) -> str:
        for attr in ("plan_id", "wbs_id", "id"):
            value = getattr(plan, attr, None)
            if value:
                return f"plan:{value}"
        tasks = SwarmTaskQueue._extract_tasks(plan)
        ids = sorted(str(SwarmTaskQueue._task_value(t, "id", "task_id")) for t in tasks)
        return "tasks:" + ",".join(ids)

    @staticmethod
    def _normalise_task(item: Any) -> QueuedTask:
        task_id = str(SwarmTaskQueue._task_value(item, "id", "task_id"))
        if not task_id or task_id == "None":
            task_id = str(uuid.uuid4())
        dependencies = tuple(str(x) for x in (getattr(item, "dependencies", None) or []))
        metadata = dict(getattr(item, "metadata", None) or {})
        capabilities = getattr(item, "capabilities", None) or metadata.get("capabilities", [])
        capabilities = tuple(
            getattr(cap, "value", str(cap)) for cap in capabilities
        )
        priority = getattr(item, "priority", 0)
        priority = getattr(priority, "value", priority)
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 0
        return QueuedTask(
            task_id=task_id,
            name=str(getattr(item, "name", task_id)),
            dependencies=dependencies,
            capabilities=capabilities,
            priority=priority,
            max_retries=int(getattr(item, "max_retries", 3)),
            metadata=metadata,
        )

    @staticmethod
    def _task_value(item: Any, *names: str) -> Any:
        for name in names:
            if isinstance(item, dict) and name in item:
                return item[name]
            value = getattr(item, name, None)
            if value is not None:
                return value
        return None
