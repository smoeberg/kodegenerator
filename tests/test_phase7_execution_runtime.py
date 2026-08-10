from infrastructure.runtime.execution import ExecutionDispatcher, ExecutionWorker


class FakeQueue:
    def __init__(self):
        self.items = []
        self.acked = []
        self.failed = []

    def enqueue(self, kind, payload, dedupe_key=None):
        item = type("Message", (), {"id": "m1", "kind": kind, "payload": payload})()
        self.items.append(item)
        return item

    def claim(self, worker_id, lease_seconds):
        return self.items.pop(0) if self.items else None

    def ack(self, message_id, worker_id):
        self.acked.append((message_id, worker_id))

    def fail(self, message_id, worker_id, error):
        self.failed.append((message_id, worker_id, error))


def test_dispatch_and_successful_worker_ack():
    queue = FakeQueue()
    dispatcher = ExecutionDispatcher(queue)
    dispatcher.dispatch("exec-1", {"task": "compile"})

    worker = ExecutionWorker(queue, lambda payload: {"ok": payload["task"]})
    result = worker.run_once("worker-1")

    assert result.status == "succeeded"
    assert result.result == {"ok": "compile"}
    assert queue.acked == [("m1", "worker-1")]


def test_worker_failure_is_not_acknowledged():
    queue = FakeQueue()
    ExecutionDispatcher(queue).dispatch("exec-2", {})

    def fail(_payload):
        raise RuntimeError("boom")

    result = ExecutionWorker(queue, fail).run_once("worker-2")

    assert result.status == "failed"
    assert queue.acked == []
    assert queue.failed[0][2] == "boom"
