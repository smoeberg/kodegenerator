"""DOR Swarm Runner CLI — start Orchestrator + workers + control plane agents.

Usage:
  python -m cli.run_swarm --workers 8 --caps domain,code,test --demo
  python -m cli.run_swarm --workers 4 --max-ticks 50 --demo --quiet

Ctrl+C triggers graceful shutdown of all worker threads and control agents.
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4


# ---------------------------------------------------------------------------
# Domain models (in-process demo swarm — no external DB required)
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    RUNNING = "running"
    TESTING = "testing"
    GATE = "gate"
    MERGED = "merged"
    FAILED = "failed"
    BLOCKED = "blocked"


class WorkerState(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    STOPPING = "stopping"
    STOPPED = "stopped"


@dataclass
class SwarmTask:
    task_id: str
    name: str
    required_caps: frozenset[str]
    status: TaskStatus = TaskStatus.PENDING
    worker_id: str | None = None
    progress: float = 0.0
    merge_status: str = "—"
    error: str | None = None


@dataclass
class WorkerAgent:
    worker_id: str
    caps: frozenset[str]
    state: WorkerState = WorkerState.IDLE
    current_task: str | None = None


@dataclass
class SwarmState:
    tasks: dict[str, SwarmTask] = field(default_factory=dict)
    workers: dict[str, WorkerAgent] = field(default_factory=dict)
    log: deque[str] = field(default_factory=lambda: deque(maxlen=200))
    stop_event: threading.Event = field(default_factory=threading.Event)
    lock: threading.RLock = field(default_factory=threading.RLock)
    ticks: int = 0
    gatekeeper_ok: int = 0
    gatekeeper_reject: int = 0
    sentinel_alerts: int = 0
    healer_actions: int = 0


# ---------------------------------------------------------------------------
# Demo project fixtures
# ---------------------------------------------------------------------------

DEMO_TASKS: list[tuple[str, str, frozenset[str]]] = [
    ("T-01", "Requirements contract", frozenset({"domain", "pm"})),
    ("T-02", "Architecture ADR", frozenset({"domain", "arch"})),
    ("T-03", "Domain model & ports", frozenset({"domain", "code"})),
    ("T-04", "API adapters", frozenset({"code"})),
    ("T-05", "Auth OAuth2/PKCE", frozenset({"code", "security"})),
    ("T-06", "Unit tests", frozenset({"test", "code"})),
    ("T-07", "Security review evidence", frozenset({"security", "test"})),
    ("T-08", "Integration tests", frozenset({"test"})),
    ("T-09", "AST architecture gate", frozenset({"test", "domain"})),
    ("T-10", "P3-20 verification pack", frozenset({"test", "security"})),
]


def load_demo_project(state: SwarmState) -> None:
    with state.lock:
        for tid, name, caps in DEMO_TASKS:
            state.tasks[tid] = SwarmTask(
                task_id=tid, name=name, required_caps=caps
            )
        _log(state, "orchestrator", f"Demo project loaded ({len(DEMO_TASKS)} tasks)")


# ---------------------------------------------------------------------------
# Logging / console
# ---------------------------------------------------------------------------


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _log(state: SwarmState, source: str, message: str) -> None:
    line = f"[{_ts()}] [{source}] {message}"
    with state.lock:
        state.log.append(line)


def print_status_line(
    task: SwarmTask,
    quiet: bool = False,
) -> None:
    if quiet:
        return
    print(
        f"  task={task.task_id:<5} worker={task.worker_id or '—':<10} "
        f"status={task.status.value:<8} progress={task.progress:5.0%} "
        f"merge={task.merge_status:<10} {task.name}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# Control-plane agents (Gatekeeper, Sentinel, Healer)
# ---------------------------------------------------------------------------


def gatekeeper_check(state: SwarmState, task: SwarmTask) -> bool:
    """Simulate AST/policy gate — reject tasks that 'fail' deterministically."""
    # Demo: T-05 occasionally needs security extra evidence
    reject = task.task_id == "T-05" and state.ticks % 7 == 0
    if reject:
        with state.lock:
            state.gatekeeper_reject += 1
        _log(state, "gatekeeper", f"REJECT {task.task_id} — policy evidence incomplete")
        return False
    with state.lock:
        state.gatekeeper_ok += 1
    _log(state, "gatekeeper", f"PASS {task.task_id} — AST + policy OK")
    return True


def sentinel_loop(state: SwarmState, poll: float = 0.4) -> None:
    """Watch for stuck / failed tasks and lease-like stalls."""
    while not state.stop_event.is_set():
        with state.lock:
            state.ticks += 1
            for task in state.tasks.values():
                if task.status == TaskStatus.FAILED:
                    state.sentinel_alerts += 1
                    _log(
                        state,
                        "sentinel",
                        f"ALERT {task.task_id} failed on {task.worker_id}: {task.error}",
                    )
                elif task.status == TaskStatus.RUNNING and task.progress < 0.05:
                    # slow start
                    pass
        state.stop_event.wait(poll)


def healer_loop(state: SwarmState, poll: float = 0.6) -> None:
    """Re-queue failed tasks (bounded retries via status reset)."""
    while not state.stop_event.is_set():
        with state.lock:
            for task in state.tasks.values():
                if task.status == TaskStatus.FAILED and task.error != "max_retries":
                    task.status = TaskStatus.PENDING
                    task.worker_id = None
                    task.progress = 0.0
                    task.merge_status = "—"
                    task.error = None
                    state.healer_actions += 1
                    _log(state, "healer", f"REQUEUE {task.task_id}")
        state.stop_event.wait(poll)


# ---------------------------------------------------------------------------
# Worker execution
# ---------------------------------------------------------------------------


def worker_loop(
    state: SwarmState,
    worker: WorkerAgent,
    work_seconds: float = 0.15,
) -> None:
    """Claim compatible pending tasks until stop."""
    while not state.stop_event.is_set():
        task: SwarmTask | None = None
        with state.lock:
            if worker.state == WorkerState.STOPPING:
                worker.state = WorkerState.STOPPED
                break
            for t in state.tasks.values():
                if t.status != TaskStatus.PENDING:
                    continue
                if not t.required_caps.issubset(worker.caps):
                    continue
                t.status = TaskStatus.CLAIMED
                t.worker_id = worker.worker_id
                worker.state = WorkerState.BUSY
                worker.current_task = t.task_id
                task = t
                break

        if task is None:
            with state.lock:
                worker.state = WorkerState.IDLE
                worker.current_task = None
            state.stop_event.wait(0.2)
            continue

        _log(state, worker.worker_id, f"CLAIM {task.task_id} {task.name}")
        # Simulate coding
        task.status = TaskStatus.RUNNING
        for step in range(1, 5):
            if state.stop_event.is_set():
                break
            task.progress = step / 5.0
            print_status_line(task)
            time.sleep(work_seconds)

        if state.stop_event.is_set():
            break

        # Testing phase
        task.status = TaskStatus.TESTING
        task.progress = 0.85
        print_status_line(task)
        time.sleep(work_seconds * 0.5)

        # Gatekeeper
        task.status = TaskStatus.GATE
        print_status_line(task)
        if not gatekeeper_check(state, task):
            task.status = TaskStatus.FAILED
            task.error = "gatekeeper_reject"
            task.merge_status = "rejected"
            print_status_line(task)
        else:
            task.status = TaskStatus.MERGED
            task.progress = 1.0
            task.merge_status = "merged"
            print_status_line(task)
            _log(state, "orchestrator", f"MERGED {task.task_id}")

        with state.lock:
            worker.state = WorkerState.IDLE
            worker.current_task = None

    with state.lock:
        worker.state = WorkerState.STOPPED
    _log(state, worker.worker_id, "STOPPED")


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def orchestrator_summary(state: SwarmState) -> dict[str, int]:
    with state.lock:
        counts: dict[str, int] = {}
        for t in state.tasks.values():
            counts[t.status.value] = counts.get(t.status.value, 0) + 1
        return counts


def all_terminal(state: SwarmState) -> bool:
    terminal = {TaskStatus.MERGED, TaskStatus.BLOCKED}
    with state.lock:
        if not state.tasks:
            return False
        return all(t.status in terminal or t.status == TaskStatus.FAILED for t in state.tasks.values()) and all(
            t.status == TaskStatus.MERGED or (t.status == TaskStatus.FAILED and t.error == "max_retries")
            for t in state.tasks.values()
        )


def project_complete(state: SwarmState) -> bool:
    with state.lock:
        if not state.tasks:
            return False
        return all(t.status == TaskStatus.MERGED for t in state.tasks.values())


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------


def parse_caps(raw: str | None) -> frozenset[str]:
    if not raw:
        return frozenset({"domain", "code", "test", "security", "arch", "pm"})
    parts = [p.strip().lower() for p in raw.replace("domein", "domain").split(",") if p.strip()]
    return frozenset(parts) if parts else frozenset({"domain", "code", "test"})


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.run_swarm",
        description="Start DOR swarm: Orchestrator + N workers + Gatekeeper + Sentinel + Healer",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of WorkerAgent threads (default: 4)",
    )
    p.add_argument(
        "--caps",
        type=str,
        default="domain,code,test,security,arch,pm",
        help="Comma-separated capability allow-list for workers",
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Load demo project fixtures and run end-to-end until merged or max-ticks",
    )
    p.add_argument(
        "--max-ticks",
        type=int,
        default=0,
        help="Stop after N sentinel ticks (0 = run until complete or Ctrl+C)",
    )
    p.add_argument(
        "--work-seconds",
        type=float,
        default=0.12,
        help="Simulated work slice per progress step (default: 0.12)",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce per-task console lines",
    )
    p.add_argument(
        "--headless",
        action="store_true",
        help="Alias for demo + quiet + finite max-ticks (for tests)",
    )
    return p


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.headless:
        args.demo = True
        args.quiet = True
        if not args.max_ticks:
            args.max_ticks = 200
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.workers > 64:
        parser.error("--workers must be <= 64")
    return args


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------


def run_swarm(args: argparse.Namespace) -> int:
    """Start swarm factory; return process exit code."""
    caps = parse_caps(args.caps)
    state = SwarmState()

    if args.demo:
        load_demo_project(state)
    else:
        _log(state, "orchestrator", "No --demo: idle swarm (Ctrl+C to stop)")

    # Workers — distribute caps so each worker gets full allow-list for demo
    for i in range(args.workers):
        wid = f"worker-{i + 1:02d}"
        state.workers[wid] = WorkerAgent(worker_id=wid, caps=caps)

    print(
        f"DOR Swarm Runner  workers={args.workers}  caps={','.join(sorted(caps))}  "
        f"demo={args.demo}",
        flush=True,
    )

    threads: list[threading.Thread] = []

    # Sentinel + Healer
    t_sent = threading.Thread(
        target=sentinel_loop, args=(state,), name="sentinel", daemon=True
    )
    t_heal = threading.Thread(
        target=healer_loop, args=(state,), name="healer", daemon=True
    )
    threads.extend([t_sent, t_heal])

    # Workers
    for wid, worker in state.workers.items():
        t = threading.Thread(
            target=worker_loop,
            args=(state, worker, args.work_seconds),
            name=wid,
            daemon=True,
        )
        threads.append(t)

    def _shutdown(signum: int | None = None, frame: Any = None) -> None:
        _log(state, "orchestrator", "Graceful shutdown requested")
        state.stop_event.set()
        with state.lock:
            for w in state.workers.values():
                if w.state != WorkerState.STOPPED:
                    w.state = WorkerState.STOPPING

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    for t in threads:
        t.start()

    exit_code = 0
    try:
        while not state.stop_event.is_set():
            if args.demo and project_complete(state):
                _log(state, "orchestrator", "All demo tasks MERGED — shutting down")
                state.stop_event.set()
                break
            if args.max_ticks and state.ticks >= args.max_ticks:
                _log(state, "orchestrator", f"max-ticks={args.max_ticks} reached")
                state.stop_event.set()
                break
            # periodic summary
            counts = orchestrator_summary(state)
            if not args.quiet:
                print(
                    f"[{_ts()}] progress={counts}  "
                    f"gate_ok={state.gatekeeper_ok} gate_rej={state.gatekeeper_reject}  "
                    f"sentinel={state.sentinel_alerts} healer={state.healer_actions}",
                    flush=True,
                )
            state.stop_event.wait(0.8)
    except KeyboardInterrupt:
        _shutdown()
        exit_code = 130

    # Join workers
    for t in threads:
        t.join(timeout=3.0)

    counts = orchestrator_summary(state)
    print("--- final ---", flush=True)
    print(f"tasks={counts}", flush=True)
    print(
        f"gatekeeper pass={state.gatekeeper_ok} reject={state.gatekeeper_reject}  "
        f"sentinel_alerts={state.sentinel_alerts} healer={state.healer_actions}",
        flush=True,
    )
    if args.demo and not project_complete(state):
        # Still ok if healer was cycling — report non-zero only if nothing merged
        with state.lock:
            merged = sum(1 for t in state.tasks.values() if t.status == TaskStatus.MERGED)
        if merged == 0:
            exit_code = 1
    return exit_code


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run_swarm(args)


if __name__ == "__main__":
    sys.exit(main())
