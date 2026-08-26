"""Dynamic capability-aware worker autoscaling."""
from __future__ import annotations

import threading
from collections import Counter
from typing import Any, Mapping


class WorkerAutoscaler:
    """Periodically sizes a worker supervisor from queue capability backlog."""

    def __init__(self, queue: Any, supervisor: Any, *, min_workers: int = 1,
                 max_workers: int = 8, interval: float = 1.0,
                 workers_per_backlog: int = 1) -> None:
        if min_workers < 0 or max_workers < min_workers:
            raise ValueError("invalid worker bounds")
        if interval <= 0 or workers_per_backlog <= 0:
            raise ValueError("interval and workers_per_backlog must be positive")
        self.queue = queue
        self.supervisor = supervisor
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.interval = interval
        self.workers_per_backlog = workers_per_backlog
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="worker-autoscaler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float | None = None) -> None:
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    def evaluate(self) -> dict[str, int]:
        backlog = self.backlog_by_capability()
        desired = self._desired_capabilities(backlog)
        self.supervisor.scale_to(desired)
        return dict(Counter(cap for caps in desired for cap in caps))

    def backlog_by_capability(self) -> dict[str, int]:
        method = getattr(self.queue, "backlog_by_capability", None)
        if callable(method):
            return {str(k): int(v) for k, v in method().items() if int(v) > 0}
        tasks = getattr(self.queue, "_tasks", {})
        counts: Counter[str] = Counter()
        for task in tasks.values():
            status = getattr(getattr(task, "status", None), "value", getattr(task, "status", None))
            if status != "PENDING":
                continue
            capabilities = getattr(task, "capabilities", ()) or ("__any__",)
            for capability in capabilities:
                counts[str(getattr(capability, "value", capability))] += 1
        return dict(counts)

    def _desired_capabilities(self, backlog: Mapping[str, int]) -> list[tuple[str, ...]]:
        total = sum(max(0, int(v)) for v in backlog.values())
        worker_count = min(self.max_workers, max(self.min_workers,
            (total + self.workers_per_backlog - 1) // self.workers_per_backlog))
        if not backlog:
            return [tuple()] * self.min_workers
        caps = sorted(backlog, key=lambda c: (-backlog[c], c))
        allocations = {cap: 1 for cap in caps[:worker_count]}
        remaining = worker_count - sum(allocations.values())
        while remaining:
            cap = max(caps, key=lambda c: backlog[c] / allocations.get(c, 1))
            allocations[cap] = allocations.get(cap, 0) + 1
            remaining -= 1
        return [tuple([cap]) for cap in caps for _ in range(allocations.get(cap, 0))]

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self.evaluate()
