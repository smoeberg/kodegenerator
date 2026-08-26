"""Test integration between DatabaseQueue messages and dashboard UI queries."""
import json
import sqlite3
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from infrastructure.runtime.queue import DatabaseQueue
from phase4.pm.human_approval import HumanApprovalQueue
from phase4.pm.inbox import ProjectManagerInbox


def test_dashboard_queue_integration(tmp_path):
    db_file = tmp_path / "test_dor.db"
    conn = sqlite3.connect(db_file)
    
    # Initialize schema using DatabaseQueue / Base
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)

    db_queue = DatabaseQueue(session_factory, lease_seconds=30)
    human_queue = HumanApprovalQueue(db_queue)
    pm_inbox = ProjectManagerInbox(db_queue)

    # Publish an approval and a PM task
    approval_id = human_queue.request_approval(
        task_id="t-100",
        title="Deploy to production database migration",
        description="Schema upgrade for new epistemics table",
        requested_by="Autonomous Agent EIRA"
    )

    task_id = pm_inbox.receive_task(
        task_id="t-101",
        title="Review Dialectical Council Report",
        description="Resolve deadlock on security policy",
        priority="urgent"
    )

    # Query from dashboard view logic
    df_queue = pd_read_query_mock = None
    # Simulate dashboard SQLite query
    cursor = conn.cursor()
    cursor.execute("SELECT id, topic, status, payload FROM runtime_queue_messages WHERE status != 'acked'")
    rows = cursor.fetchall()
    
    assert len(rows) == 2
    topics = [r[1] for r in rows]
    assert "human.approvals" in topics
    assert "pm.inbox" in topics

    # Simulate dashboard approval action (ACK)
    cursor.execute("UPDATE runtime_queue_messages SET status = 'acked' WHERE id = ?", (approval_id,))
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM runtime_queue_messages WHERE status != 'acked'")
    remaining = cursor.fetchone()[0]
    assert remaining == 1
    conn.close()
