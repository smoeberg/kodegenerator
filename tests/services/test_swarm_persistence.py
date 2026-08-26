from datetime import datetime, timedelta, timezone
from services.swarm_persistence import SQLiteTaskQueue
from services.swarm_task_queue import QueuedTask


def make_task(task_id="T1"):
    return QueuedTask(task_id=task_id,name=task_id,capabilities=("code",))


def test_restart_resumes_claim(tmp_path):
    db=tmp_path/"swarm.db"
    q=SQLiteTaskQueue(db,lease_seconds=300)
    q.submit_task(make_task())
    assert q.claim_next_task("agent-a",["code"]).task_id=="T1"
    q.close()
    q=SQLiteTaskQueue(db,lease_seconds=300)
    assert q.get_task("T1").agent_id=="agent-a"
    assert q.claim_next_task("agent-b",["code"]) is None


def test_submit_is_idempotent(tmp_path):
    q=SQLiteTaskQueue(tmp_path/"q.db")
    assert q.submit_task(make_task())=="T1"
    assert q.submit_task(make_task())=="T1"
    assert q.get_queue_stats()["pending"]==1


def test_expired_lease_recovery_after_restart(tmp_path):
    now=datetime(2026,8,26,10,0,tzinfo=timezone.utc)
    clock=lambda: now
    db=tmp_path/"q.db"
    q=SQLiteTaskQueue(db,lease_seconds=10,clock=clock)
    q.submit_task(make_task()); q.claim_next_task("crashed",["code"]); q.close()
    now += timedelta(seconds=11)
    q=SQLiteTaskQueue(db,lease_seconds=10,clock=clock)
    recovered=q.claim_next_task("replacement",["code"])
    assert recovered and recovered.task_id=="T1" and recovered.agent_id=="replacement"
