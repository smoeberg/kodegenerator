import threading
import time

from services.swarm_supervisor import SwarmSupervisor


class FakeWorker:
    def __init__(self, agent_id, capabilities, *, crash=False):
        self.agent_id = agent_id
        self.capabilities = capabilities
        self.crash = crash
        self.total_tasks_completed = 0
        self.stop_event = threading.Event()

    def run(self):
        if self.crash:
            return
        while not self.stop_event.wait(0.01):
            pass

    def stop(self):
        self.stop_event.set()


def wait_until(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_starts_pool_with_mixed_capabilities():
    workers = []

    def factory(agent_id, capabilities):
        worker = FakeWorker(agent_id, capabilities)
        workers.append(worker)
        return worker

    supervisor = SwarmSupervisor(factory, [["code"], ["security", "code"]], health_interval=0.01)
    supervisor.start()
    try:
        assert wait_until(lambda: supervisor.active_workers == 2)
        assert {tuple(w.capabilities) for w in workers} == {("code",), ("security", "code")}
    finally:
        supervisor.stop()
        supervisor.join(1)


def test_restarts_crashed_worker_thread():
    workers = []

    def factory(agent_id, capabilities):
        worker = FakeWorker(agent_id, capabilities, crash=not workers)
        workers.append(worker)
        return worker

    supervisor = SwarmSupervisor(factory, [["code"]], health_interval=0.01)
    supervisor.start()
    try:
        assert wait_until(lambda: len(workers) >= 2)
        assert supervisor.active_workers == 1
    finally:
        supervisor.stop()
        supervisor.join(1)


def test_clean_shutdown_leaves_no_worker_or_supervisor_threads():
    supervisor = SwarmSupervisor(lambda agent_id, capabilities: FakeWorker(agent_id, capabilities), [["code"], ["test"]], health_interval=0.01)
    supervisor.start()
    assert wait_until(lambda: supervisor.active_workers == 2)
    supervisor.stop()
    supervisor.join(1)
    assert supervisor.active_workers == 0
    assert supervisor._monitor is None or not supervisor._monitor.is_alive()
    assert all(slot.thread is None or not slot.thread.is_alive() for slot in supervisor._workers)
