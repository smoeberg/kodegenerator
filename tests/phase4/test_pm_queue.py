"""Unit tests for the Project Manager & Orchestrator Inbox Queue."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from infrastructure.runtime.queue import DatabaseQueue
from phase4.pm.inbox import ProjectManagerInbox


@pytest.fixture
def db_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_pm_inbox_lifecycle(db_session_factory):
    db_queue = DatabaseQueue(db_session_factory, lease_seconds=30)
    pm_inbox = ProjectManagerInbox(db_queue)

    # 1. Human / System enqueues a brief into PM inbox
    msg_id = pm_inbox.receive_task(
        task_id="task-999",
        title="Implement OAuth2 token rotation",
        description="Secure token refresh flow",
        priority="high",
        payload={"module": "auth"}
    )
    assert msg_id is not None

    # 2. PM bot polls its inbox
    claimed = pm_inbox.poll_pm_inbox(worker_id="pm-bot-1")
    assert claimed is not None
    assert claimed.id == msg_id
    assert claimed.payload["task_id"] == "task-999"
    assert claimed.payload["priority"] == "high"

    # 3. PM dispatches sub-task to Coder bot
    dispatch_id = pm_inbox.dispatch_to_specialist(
        task_id="task-999",
        target_role="Coder",
        instruction="Write token rotation service",
        context={"file": "auth/tokens.py"}
    )
    assert dispatch_id is not None

    # 4. Coder bot claims the dispatch
    coder_claimed = pm_inbox.poll_specialist_dispatch(worker_id="coder-bot-1")
    assert coder_claimed is not None
    assert coder_claimed.id == dispatch_id
    assert coder_claimed.payload["target_role"] == "Coder"

    # 5. Coder acknowledges completion
    pm_inbox.ack_message(coder_claimed.id, worker_id="coder-bot-1")

    # 6. PM acknowledges task processing
    pm_inbox.ack_message(claimed.id, worker_id="pm-bot-1")


def test_pm_escalation(db_session_factory):
    db_queue = DatabaseQueue(db_session_factory, lease_seconds=30)
    pm_inbox = ProjectManagerInbox(db_queue)

    esc_id = pm_inbox.escalate_deadlock(
        session_id="sess-deadlock-1",
        task_id="task-888",
        reason="Council reached max rounds without consensus on database migration schema."
    )
    assert esc_id is not None
