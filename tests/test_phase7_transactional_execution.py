from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from domain.task_execution import TaskExecutionRequest
from infrastructure.persistence.models import Base, TaskExecutionModel
from infrastructure.runtime.queue import QueueMessageModel
from infrastructure.runtime.transactional_execution import TransactionalExecutionDispatcher
from infrastructure.runtime.queue import DatabaseQueue


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[TaskExecutionModel.__table__, QueueMessageModel.__table__])
    return Session(engine)


def test_receipt_and_queue_message_commit_together():
    session = _session()
    dispatcher = TransactionalExecutionDispatcher(DatabaseQueue(lambda: session))
    request = TaskExecutionRequest(
        execution_id="exec-atomic",
        organization_id="org-1",
        actor_id="actor-1",
        task_type="compile",
        capability_id="compile",
        payload={"source": "x"},
    )

    dispatcher.dispatch(session, request)
    session.commit()

    assert session.scalar(select(TaskExecutionModel).where(TaskExecutionModel.execution_id == "exec-atomic"))
    assert session.scalar(select(QueueMessageModel).where(QueueMessageModel.id == "execution:exec-atomic"))


def test_rollback_removes_receipt_and_queue_message():
    session = _session()
    dispatcher = TransactionalExecutionDispatcher(DatabaseQueue(lambda: session))
    request = TaskExecutionRequest(
        execution_id="exec-rollback",
        organization_id="org-1",
        actor_id="actor-1",
        task_type="compile",
        capability_id="compile",
    )

    dispatcher.dispatch(session, request)
    session.rollback()

    assert session.scalar(select(TaskExecutionModel).where(TaskExecutionModel.execution_id == "exec-rollback")) is None
    assert session.scalar(select(QueueMessageModel).where(QueueMessageModel.id == "execution:exec-rollback")) is None
