from infrastructure.runtime.execution import ExecutionDispatcher, ExecutionWorker


class FakeQueue:
    def __init__(self):
        self.items = []
        self.acked = []
        self.failed = []

    def publish(self, topic, payload, message_id=None):
        self.items.append(type("Message", (), {"id": message_id, "topic": topic, "payload": payload, "lease_id": "lease-1"})())
        return message_id

    def claim(self, topic, worker_id):
        return self.items.pop(0) if self.items else None

    def ack(self, message_id, worker_id, lease_id):
        self.acked.append((message_id, worker_id, lease_id))

    def fail(self, message_id, worker_id, lease_id, error):
        self.failed.append((message_id, worker_id, lease_id, error))


def test_dispatch_and_successful_worker_ack():
    queue = FakeQueue()
    ExecutionDispatcher(queue).dispatch("exec-1", {"task": "compile"})

    result = ExecutionWorker(queue, lambda payload: {"ok": payload["task"]}).run_once("worker-1")

    assert result.status == "succeeded"
    assert result.result == {"ok": "compile"}
    assert queue.acked == [("execution:exec-1", "worker-1", "lease-1")]


def test_worker_failure_is_not_acknowledged():
    queue = FakeQueue()
    ExecutionDispatcher(queue).dispatch("exec-2", {})

    def fail(_payload):
        raise RuntimeError("boom")

    result = ExecutionWorker(queue, fail).run_once("worker-2")

    assert result.status == "failed"
    assert queue.acked == []
    assert queue.failed[0][3] == "boom"
