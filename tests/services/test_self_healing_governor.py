from datetime import datetime, timedelta, timezone

from services.self_healing_governor import CircuitState, SelfHealingGovernor


def test_moves_to_dlq_after_max_retries():
    clock = lambda: datetime(2026, 8, 26, tzinfo=timezone.utc)
    governor = SelfHealingGovernor(max_retries=2, clock=clock)
    governor.record_failure("task-1", "boom", "worker-1")
    governor.record_failure("task-1", "boom again", "worker-1")
    assert governor.dlq.get("task-1") is None
    governor.record_failure("task-1", "fatal", "worker-1")
    letter = governor.dlq.get("task-1")
    assert letter is not None
    assert len(letter.failures) == 3
    assert letter.failures[-1].stack_trace


def test_exponential_backoff_is_bounded():
    clock = lambda: datetime(2026, 8, 26, tzinfo=timezone.utc)
    governor = SelfHealingGovernor(max_retries=10, base_backoff_seconds=2, max_backoff_seconds=5, clock=clock)
    first = governor.record_failure("task", "e", "w")
    second = governor.record_failure("task", "e", "w")
    third = governor.record_failure("task", "e", "w")
    assert (first.retry_at - first.recorded_at).total_seconds() == 2
    assert (second.retry_at - second.recorded_at).total_seconds() == 4
    assert (third.retry_at - third.recorded_at).total_seconds() == 5


def test_circuit_breaker_opens_and_closes_after_cooldown():
    now = [datetime(2026, 8, 26, tzinfo=timezone.utc)]
    governor = SelfHealingGovernor(circuit_threshold=0.5, circuit_window_seconds=60, circuit_cooldown_seconds=10, clock=lambda: now[0])
    governor.record_outcome("security", False)
    assert governor.get_circuit_state("security") == CircuitState.OPEN
    assert not governor.dispatch_allowed("security")
    now[0] += timedelta(seconds=11)
    assert governor.dispatch_allowed("security")
    assert governor.get_circuit_state("security") == CircuitState.HALF_OPEN
    governor.record_outcome("security", True)
    assert governor.get_circuit_state("security") == CircuitState.CLOSED
    assert governor.dispatch_allowed("security")


def test_worker_quarantine_does_not_affect_healthy_worker():
    governor = SelfHealingGovernor()
    governor.quarantine_worker("bad-worker")
    assert governor.is_quarantined("bad-worker")
    assert not governor.is_quarantined("healthy-worker")
    governor.release_worker("bad-worker")
    assert not governor.is_quarantined("bad-worker")
