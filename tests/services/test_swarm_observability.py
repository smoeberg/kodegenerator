from datetime import datetime, timedelta, timezone

from services.swarm_observability import SwarmAuditLog, SwarmEventType, SwarmMetrics


def test_audit_chain_and_event_order():
    log = SwarmAuditLog()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    first = log.append(SwarmEventType.PROJECT_STARTED, project_id="p", timestamp=base)
    second = log.append(SwarmEventType.TASK_CLAIMED, worker_id="w", task_id="t", project_id="p", timestamp=base + timedelta(seconds=2))
    third = log.append(SwarmEventType.TASK_COMPLETED, worker_id="w", task_id="t", project_id="p", timestamp=base + timedelta(seconds=7))

    assert first.event_hash != second.event_hash
    assert second.event_hash != third.event_hash
    assert [e.event_type for e in log.events()] == [
        "PROJECT_STARTED", "TASK_CLAIMED", "TASK_COMPLETED"
    ]
    assert log.verify_chain()


def test_tampering_breaks_chain():
    log = SwarmAuditLog()
    log.append(SwarmEventType.PROJECT_STARTED, project_id="p")
    log.append(SwarmEventType.HEARTBEAT, worker_id="w", task_id="t", project_id="p")
    assert log.verify_chain()
    log._db.execute("UPDATE swarm_audit_events SET payload=? WHERE sequence=1", ('{"tampered":true}',))
    log._db.commit()
    assert not log.verify_chain()


def test_metrics_aggregation():
    log = SwarmAuditLog()
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    log.append(SwarmEventType.TASK_CLAIMED, worker_id="w", task_id="t1", timestamp=base)
    log.append(SwarmEventType.TASK_COMPLETED, worker_id="w", task_id="t1", timestamp=base + timedelta(seconds=10))
    log.append(SwarmEventType.TASK_CLAIMED, worker_id="w", task_id="t2", timestamp=base + timedelta(seconds=20))
    log.append(SwarmEventType.TASK_FAILED, worker_id="w", task_id="t2", timestamp=base + timedelta(seconds=30))
    log.append(SwarmEventType.MERGE_APPROVED, project_id="p", payload={"merge_started_at": (base + timedelta(seconds=40)).isoformat()}, timestamp=base + timedelta(seconds=43))

    snapshot = SwarmMetrics(log).snapshot()
    assert snapshot.tasks_claimed == 2
    assert snapshot.tasks_completed == 1
    assert snapshot.tasks_failed == 1
    assert snapshot.avg_claim_duration == 10.0
    assert snapshot.merge_latency == 3.0
