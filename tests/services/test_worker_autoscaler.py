import threading
import time

from services.swarm_supervisor import SwarmSupervisor
from services.worker_autoscaler import WorkerAutoscaler


class FakeWorker:
    def __init__(self, agent_id, capabilities):
        self.agent_id = agent_id
        self.capabilities = capabilities
        self.stop_event = threading.Event()

    def run(self):
        self.stop_event.wait()

    def stop(self):
        self.stop_event.set()


class FakeQueue:
    def __init__(self, backlog):
        self.backlog = dict(backlog)

    def backlog_by_capability(self):
        return self.backlog


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def make_supervisor():
    return SwarmSupervisor(lambda agent_id, capabilities: FakeWorker(agent_id, capabilities), [()])


def test_scales_up_for_large_wbs_backlog():
    queue = FakeQueue({"code": 12})
    supervisor = make_supervisor()
    supervisor.start()
    autoscaler = WorkerAutoscaler(queue, supervisor, min_workers=1, max_workers=6, workers_per_backlog=2)
    try:
        result = autoscaler.evaluate()
        assert result["code"] == 6
        assert wait_until(lambda: supervisor.active_workers == 6)
    finally:
        supervisor.stop()
        supervisor.join(1)


def test_scales_down_to_minimum_when_queue_drains():
    queue = FakeQueue({"code": 8})
    supervisor = make_supervisor()
    supervisor.start()
    autoscaler = WorkerAutoscaler(queue, supervisor, min_workers=1, max_workers=6, workers_per_backlog=2)
    try:
        autoscaler.evaluate()
        assert wait_until(lambda: supervisor.active_workers == 4)
        queue.backlog = {}
        autoscaler.evaluate()
        assert wait_until(lambda: supervisor.active_workers == 1)
    finally:
        supervisor.stop()
        supervisor.join(1)


def test_rebalances_toward_high_security_backlog():
    queue = FakeQueue({"code": 2, "security": 10})
    supervisor = make_supervisor()
    supervisor.start()
    autoscaler = WorkerAutoscaler(queue, supervisor, min_workers=1, max_workers=6, workers_per_backlog=3)
    try:
        autoscaler.evaluate()
        assert wait_until(lambda: supervisor.active_workers == 4)
        capabilities = [s.capabilities[0] for s in supervisor._workers if s.thread and s.thread.is_alive() and not s.draining]
        assert capabilities.count("security") > capabilities.count("code")
    finally:
        supervisor.stop()
        supervisor.join(1)
