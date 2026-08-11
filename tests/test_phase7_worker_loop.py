from infrastructure.runtime.worker_loop import WorkerLoop


def test_worker_loop_stops_after_requested_iterations():
    calls = []
    loop = WorkerLoop(lambda: calls.append(1), poll_seconds=0)
    assert loop.run(max_iterations=3) == 3
    assert len(calls) == 3


def test_worker_loop_can_be_stopped():
    loop = WorkerLoop(lambda: loop.stop(), poll_seconds=0)
    assert loop.run() == 1
