"""Regression tests for durable queue lease fencing and dead-lettering."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.persistence.models import Base
from infrastructure.runtime.queue import DatabaseQueue, QueueMessageModel


def _queue(*, max_attempts: int = 3) -> tuple[DatabaseQueue, sessionmaker[Session]]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[QueueMessageModel.__table__])
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    return DatabaseQueue(factory, lease_seconds=60, max_attempts=max_attempts), factory


def _expire(factory: sessionmaker[Session], message_id: str) -> None:
    with factory() as session:
        row = session.scalar(
            select(QueueMessageModel).where(QueueMessageModel.id == message_id)
        )
        assert row is not None
        row.lease_until = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()


def test_stale_lease_cannot_ack_reclaimed_message() -> None:
    queue, factory = _queue()
    message_id = queue.publish("execution", {"value": 1})
    first = queue.claim("execution", "worker-a")
    assert first is not None and first.lease_id

    _expire(factory, message_id)
    second = queue.claim("execution", "worker-a")
    assert second is not None and second.lease_id
    assert second.lease_id != first.lease_id

    with pytest.raises(ValueError, match="not leased"):
        queue.ack(first.id, "worker-a", first.lease_id)

    queue.ack(second.id, "worker-a", second.lease_id)
    with factory() as session:
        row = session.get(QueueMessageModel, message_id)
        assert row is not None
        assert row.status == "completed"


def test_failure_moves_message_to_dead_letter_at_max_attempts() -> None:
    queue, factory = _queue(max_attempts=2)
    message_id = queue.publish("execution", {"value": 1})

    first = queue.claim("execution", "worker-a")
    assert first is not None and first.lease_id
    queue.fail(first.id, "worker-a", first.lease_id, "first", retry_after_seconds=0)

    second = queue.claim("execution", "worker-b")
    assert second is not None and second.lease_id
    queue.fail(second.id, "worker-b", second.lease_id, "second", retry_after_seconds=0)

    assert queue.claim("execution", "worker-c") is None
    assert queue.dead_letter_count("execution") == 1
    with factory() as session:
        row = session.get(QueueMessageModel, message_id)
        assert row is not None
        assert row.status == "dead_letter"
        assert row.last_error == "second"


def test_expired_final_attempt_is_dead_lettered_instead_of_reclaimed() -> None:
    queue, factory = _queue(max_attempts=1)
    message_id = queue.publish("execution", {"value": 1})
    claimed = queue.claim("execution", "worker-a")
    assert claimed is not None

    _expire(factory, message_id)

    assert queue.claim("execution", "worker-b") is None
    assert queue.dead_letter_count() == 1
