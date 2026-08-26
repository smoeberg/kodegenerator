"""Tests for Human Approval Queue timeout and fallback policies."""
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from infrastructure.runtime.queue import DatabaseQueue, Base
from phase4.pm.human_approval import HumanApprovalQueue


def test_approval_request_with_ttl(tmp_path):
    db_path = str(tmp_path / "test_queue.db")
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    
    db_queue = DatabaseQueue(session_factory, lease_seconds=30)
    approval_q = HumanApprovalQueue(db_queue)

    msg_id = approval_q.request_approval(
        task_id="task-123",
        title="Deploy Critical Refactor",
        description="Requires human signoff",
        requested_by="ai-pm",
        fallback_policy="AUTO_REJECT",
        timeout_hours=12
    )

    assert msg_id is not None
    claimed = approval_q.poll_pending_approvals(worker_id="test-worker")
    assert claimed is not None
    assert claimed.payload["title"] == "Deploy Critical Refactor"
    assert claimed.payload["fallback_policy"] == "AUTO_REJECT"
    assert claimed.payload["status"] == "PENDING"
