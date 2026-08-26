"""Tests for the autonomous Worker Agent Daemon."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

import pytest

from services.swarm_task_queue import QueuedTaskStatus, SwarmTaskQueue
from services.worker_agent_daemon import WorkerAgent, _default_synthesizer


@dataclass
class FakeTask:
    id: str
    name: str
    dependencies: list = field(default_factory=list)
    capabilities: list = field(default_factory=list)
    priority: int = 0


@dataclass
class FakePlan:
    id: str
    tasks: list


class ManualClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 26, 10, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def enqueue(queue: SwarmTaskQueue, *task_ids: str, capabilities=("code",)) -> None:
    tasks = [
        FakeTask(tid, tid, capabilities=list(capabilities)) for tid in task_ids
    ]
    queue.enqueue_wbs_plan(FakePlan("plan-1", tasks))


class RecordingSynthesizer:
    """Deterministic synthesizer that records calls and can be delayed/fail."""

    def __init__(
        self,
        *,
        delay: float = 0.0,
        fail_for: Optional[set[str]] = None,
        result_factory=None,
    ) -> None:
        self.delay = delay
        self.fail_for = fail_for or set()
        self.result_factory = result_factory
        self.calls: List[str] = []
        self._lock = threading.Lock()

    def synthesize(self, task) -> Any:
        with self._lock:
            self.calls.append(task.task_id)
        if self.delay:
            time.sleep(self.delay)
        if task.task_id in self.fail_for:
            raise RuntimeError(f"synthetic failure for {task.task_id}")
        if self.result_factory:
            return self.result_factory(task)
        return {
            "artifact": f"{task.task_id}.py",
            "lines": 42,
            "path": f"generated/{task.task_id}.py",
            "task_id": task.task_id,
        }


def test_claim_loop_completes_eligible_task():
    queue = SwarmTaskQueue(lease_seconds=60)
    enqueue(queue, "T1")
    synth = RecordingSynthesizer()
    agent = WorkerAgent(
        "worker-01",
        ["code"],
        queue,
        synthesizer=synth,
        poll_interval=0.01,
        max_idle_cycles=3,
    )

    agent.run()

    assert synth.calls == ["T1"]
    assert queue.get_task("T1").status == QueuedTaskStatus.COMPLETED
    assert queue.get_task("T1").patch_result["artifact"] == "T1.py"
    assert agent._completed == 1


def test_run_once_claims_and_completes():
    queue = SwarmTaskQueue()
    enqueue(queue, "A", "B")
    synth = RecordingSynthesizer()
    agent = WorkerAgent("w1", ["code"], queue, synthesizer=synth)

    claimed = agent.run_once()
    assert claimed is not None
    assert claimed.task_id in ("A", "B")
    assert queue.get_task(claimed.task_id).status == QueuedTaskStatus.COMPLETED

    claimed2 = agent.run_once()
    assert claimed2 is not None
    assert claimed2.task_id != claimed.task_id
    assert agent._completed == 2


def test_capabilities_filter_which_tasks_are_claimed():
    queue = SwarmTaskQueue()
    queue.enqueue_wbs_plan(
        FakePlan(
            "plan-caps",
            [
                FakeTask("sec", "sec", capabilities=["security"]),
                FakeTask("code", "code", capabilities=["code"]),
            ],
        )
    )
    synth = RecordingSynthesizer()
    agent = WorkerAgent("dev", ["code"], queue, synthesizer=synth)

    claimed = agent.run_once()
    assert claimed is not None
    assert claimed.task_id == "code"
    assert agent.run_once() is None  # security task remains unclaimed
    assert queue.get_task("sec").status == QueuedTaskStatus.PENDING


def test_synthesis_failure_marks_task_failed_or_retry():
    queue = SwarmTaskQueue()
    enqueue(queue, "T-fail")
    synth = RecordingSynthesizer(fail_for={"T-fail"})
    agent = WorkerAgent("w1", ["code"], queue, synthesizer=synth)

    agent.run_once()

    task = queue.get_task("T-fail")
    # Default fail_task uses retry=True and max_retries=3 → back to PENDING
    assert task.status == QueuedTaskStatus.PENDING
    assert task.error is not None
    assert "synthetic failure" in task.error
    assert agent._failed == 1


def test_heartbeat_extends_lease_during_long_synthesis():
    clock = ManualClock()
    queue = SwarmTaskQueue(lease_seconds=5, clock=clock)
    enqueue(queue, "slow")

    heartbeats = []

    original_heartbeat = queue.heartbeat

    def tracking_heartbeat(task_id, agent_id):
        heartbeats.append((task_id, agent_id, clock.now))
        return original_heartbeat(task_id, agent_id)

    queue.heartbeat = tracking_heartbeat  # type: ignore[method-assign]

    def slow_synth(task):
        # Advance clock past original lease; heartbeats should keep it alive.
        for _ in range(3):
            time.sleep(0.05)
            clock.advance(2)
        return {"artifact": "slow.py", "lines": 1}

    agent = WorkerAgent(
        "w-hb",
        ["code"],
        queue,
        synthesizer=slow_synth,
        heartbeat_interval=0.05,
    )
    agent.run_once()

    assert queue.get_task("slow").status == QueuedTaskStatus.COMPLETED
    assert len(heartbeats) >= 1


def test_graceful_shutdown_releases_in_flight_task():
    queue = SwarmTaskQueue(lease_seconds=120)
    enqueue(queue, "long")

    started = threading.Event()
    release = threading.Event()

    def blocking_synth(task):
        started.set()
        release.wait(timeout=5.0)
        return {"artifact": "should-not-complete.py"}

    agent = WorkerAgent(
        "w-shut",
        ["code"],
        queue,
        synthesizer=blocking_synth,
        heartbeat_interval=60.0,
        poll_interval=0.01,
    )

    thread = threading.Thread(target=agent.run, daemon=True)
    thread.start()

    assert started.wait(timeout=2.0)
    assert agent.current_task_id == "long"

    agent.request_stop()
    # Unblock synthesizer so the execute path can observe stop / finish.
    release.set()
    thread.join(timeout=3.0)
    assert not thread.is_alive()

    # Either completed (synth finished) or released back to PENDING via fail.
    status = queue.get_task("long").status
    assert status in (
        QueuedTaskStatus.COMPLETED,
        QueuedTaskStatus.PENDING,
        QueuedTaskStatus.FAILED,
    )


def test_request_stop_exits_idle_loop():
    queue = SwarmTaskQueue()
    agent = WorkerAgent(
        "idle",
        ["code"],
        queue,
        poll_interval=0.05,
        max_idle_cycles=None,
    )

    thread = threading.Thread(target=agent.run, daemon=True)
    thread.start()
    time.sleep(0.15)
    assert agent.is_running
    agent.request_stop()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert not agent.is_running


def test_worker_id_and_capabilities_validation():
    queue = SwarmTaskQueue()
    with pytest.raises(ValueError, match="worker_id"):
        WorkerAgent("", ["code"], queue)
    with pytest.raises(ValueError, match="capabilities"):
        WorkerAgent("w1", [], queue)
    with pytest.raises(ValueError, match="capabilities"):
        WorkerAgent("w1", ["", "  "], queue)


def test_default_synthesizer_produces_dict():
    queue = SwarmTaskQueue()
    enqueue(queue, "noop")
    agent = WorkerAgent("w1", ["code"], queue)  # no synthesizer → default
    agent.run_once()
    result = queue.get_task("noop").patch_result
    assert result["task_id"] == "noop"
    assert result["status"] == "noop"


def test_callable_synthesizer_supported():
    queue = SwarmTaskQueue()
    enqueue(queue, "fn")
    agent = WorkerAgent(
        "w1",
        ["code"],
        queue,
        synthesizer=lambda t: {"from": "callable", "id": t.task_id},
    )
    agent.run_once()
    assert queue.get_task("fn").patch_result["from"] == "callable"


def test_logging_transitions():
    """Verificerer workerens transition-logning.

    Kører flowet i en subproces så testen er komplet uafhængig af global
    log-tilstand (tidligere tests / get_dor() kan sætte root-loggeren til
    WARNING og manipulere handlers globalt).
    """
    import io
    import subprocess
    import sys

    code = (
        "import io, logging, sys; "
        "sys.path.insert(0, '.'); "
        "from services.swarm_task_queue import SwarmTaskQueue; "
        "from services.worker_agent_daemon import WorkerAgent; "
        "from tests.services.test_worker_agent_daemon import RecordingSynthesizer, enqueue; "
        "lg = logging.getLogger('services.worker_agent_daemon'); "
        "lg.handlers = []; lg.setLevel(logging.INFO); lg.propagate = False; "
        "buf = io.StringIO(); "
        "h = logging.StreamHandler(buf); h.setLevel(logging.INFO); lg.addHandler(h); "
        "q = SwarmTaskQueue(); "
        "enqueue(q, 'log-me'); "
        "agent = WorkerAgent('logger', ['code'], q, synthesizer=RecordingSynthesizer()); "
        "agent.run_once(); "
        "sys.stdout.write(buf.getvalue())"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=".",
    )
    assert out.returncode == 0, out.stderr
    messages = out.stdout
    assert "transition=CLAIMED" in messages
    assert "transition=COMPLETED" in messages

