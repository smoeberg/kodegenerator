"""Supervisor for a pool of WorkerAgent-compatible worker daemons."""
from __future__ import annotations

import signal
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional


@dataclass
class _WorkerSlot:
    index: int
    capabilities: tuple[str, ...]
    worker: Any = None
    thread: Optional[threading.Thread] = None
    completed_baseline: int = 0
    draining: bool = False


class SwarmSupervisor:
    """Owns worker lifecycles, crash recovery, and graceful scaling."""

    def __init__(self, worker_factory: Callable[..., Any], worker_capabilities: Iterable[Iterable[str]], *, health_interval: float = 0.25) -> None:
        if health_interval <= 0:
            raise ValueError("health_interval must be positive")
        self.worker_factory = worker_factory
        self.worker_capabilities = [tuple(c) for c in worker_capabilities]
        if not self.worker_capabilities:
            raise ValueError("at least one worker capability set is required")
        self.health_interval = health_interval
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor: Optional[threading.Thread] = None
        self._started_at: Optional[float] = None
        self._workers: list[_WorkerSlot] = []
        self._completed = 0
        self._signals_installed = False

    def start(self) -> None:
        with self._lock:
            if self._monitor and self._monitor.is_alive():
                return
            self._stop_event.clear()
            self._started_at = time.monotonic()
            self._workers = [_WorkerSlot(i, caps) for i, caps in enumerate(self.worker_capabilities)]
            for slot in self._workers:
                self._start_slot(slot)
            self._install_signal_handlers()
            self._monitor = threading.Thread(target=self._health_loop, name="swarm-supervisor", daemon=True)
            self._monitor.start()

    def scale_to(self, capabilities: Iterable[Iterable[str]]) -> None:
        """Adjust pool size; removed workers are asked to drain and stop."""
        desired = [tuple(c) for c in capabilities]
        with self._lock:
            if self._monitor is None or not self._monitor.is_alive():
                self.worker_capabilities = desired
                return
            active = [s for s in self._workers if s.thread and s.thread.is_alive() and not s.draining]
            used: set[int] = set()
            for caps in desired:
                match = next((s for s in active if s.index not in used and s.capabilities == caps), None)
                if match is None:
                    continue
                used.add(match.index)
            for slot in active:
                if slot.index not in used:
                    slot.draining = True
                    self._stop_worker(slot.worker)
            next_index = max((s.index for s in self._workers), default=-1) + 1
            for caps in desired:
                if any(s.index in used and s.capabilities == caps for s in active):
                    continue
                slot = _WorkerSlot(next_index, caps)
                next_index += 1
                self._workers.append(slot)
                self._start_slot(slot)
            self.worker_capabilities = desired

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            workers = [slot.worker for slot in self._workers]
        for worker in workers:
            self._stop_worker(worker)

    def join(self, timeout: Optional[float] = None) -> None:
        monitor = self._monitor
        if monitor and monitor is not threading.current_thread():
            monitor.join(timeout)
        deadline = None if timeout is None else time.monotonic() + timeout
        for slot in list(self._workers):
            thread = slot.thread
            if thread and thread is not threading.current_thread():
                remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
                thread.join(remaining)

    @property
    def active_workers(self) -> int:
        with self._lock:
            return sum(bool(s.thread and s.thread.is_alive() and not s.draining) for s in self._workers)

    @property
    def total_tasks_completed(self) -> int:
        with self._lock:
            total = self._completed
            for slot in self._workers:
                total += max(0, self._worker_completed(slot.worker) - slot.completed_baseline)
            return max(0, total)

    @property
    def uptime_seconds(self) -> float:
        started = self._started_at
        return 0.0 if started is None else max(0.0, time.monotonic() - started)

    def status(self) -> dict[str, float | int]:
        return {"active_workers": self.active_workers, "total_tasks_completed": self.total_tasks_completed, "uptime_seconds": self.uptime_seconds}

    def _start_slot(self, slot: _WorkerSlot) -> None:
        worker = self._make_worker(slot.capabilities, slot.index)
        thread = threading.Thread(target=self._run_worker, args=(slot, worker), name=f"swarm-worker-{slot.index}", daemon=True)
        slot.worker, slot.thread = worker, thread
        slot.completed_baseline = self._worker_completed(worker)
        thread.start()

    def _run_worker(self, slot: _WorkerSlot, worker: Any) -> None:
        try:
            run = getattr(worker, "run", None) or getattr(worker, "start", None)
            if run is None:
                raise AttributeError("worker must expose run() or start()")
            run()
        finally:
            with self._lock:
                self._completed += max(0, self._worker_completed(worker) - slot.completed_baseline)
                slot.completed_baseline = self._worker_completed(worker)

    def _health_loop(self) -> None:
        while not self._stop_event.wait(self.health_interval):
            with self._lock:
                for slot in self._workers:
                    if slot.thread and not slot.thread.is_alive() and not slot.draining and not self._stop_event.is_set():
                        self._start_slot(slot)

    def _make_worker(self, capabilities: tuple[str, ...], index: int) -> Any:
        try:
            return self.worker_factory(agent_id=f"worker-{index}", capabilities=list(capabilities))
        except TypeError:
            return self.worker_factory(list(capabilities))

    @staticmethod
    def _stop_worker(worker: Any) -> None:
        if worker is None:
            return
        for name in ("stop", "shutdown", "close"):
            method = getattr(worker, name, None)
            if callable(method):
                method()
                return

    @staticmethod
    def _worker_completed(worker: Any) -> int:
        if worker is None:
            return 0
        value = getattr(worker, "total_tasks_completed", getattr(worker, "tasks_completed", 0))
        try:
            return int(value() if callable(value) else value)
        except (TypeError, ValueError):
            return 0

    def _install_signal_handlers(self) -> None:
        if self._signals_installed or threading.current_thread() is not threading.main_thread():
            return
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)
        self._signals_installed = True

    def _handle_signal(self, _signum: int, _frame: Any) -> None:
        self.stop()
