"""Durable database-backed queue primitives for Phase 7 workers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Integer, JSON, String, Text, select, update
from sqlalchemy.orm import Session, Mapped, mapped_column

from infrastructure.persistence.models import Base


class QueueMessageModel(Base):
    __tablename__ = "runtime_queue_messages"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class QueueMessage:
    id: str
    topic: str
    payload: dict[str, Any]
    attempts: int


class DatabaseQueue:
    """At-least-once queue using the application's durable SQL database.

    Claiming uses a short transaction and a lease. A worker crash therefore
    leaves work recoverable instead of silently losing the message.
    """

    def __init__(self, session_factory, lease_seconds: int = 60):
        self.session_factory = session_factory
        self.lease_seconds = lease_seconds

    def publish(self, topic: str, payload: dict[str, Any], message_id: str | None = None) -> str:
        now = datetime.now(timezone.utc)
        message_id = message_id or str(uuid4())
        with self.session_factory() as session:
            session.add(
                QueueMessageModel(
                    id=message_id,
                    topic=topic,
                    payload=payload,
                    status="pending",
                    attempts=0,
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
        return message_id

    def claim(self, topic: str, worker_id: str) -> QueueMessage | None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            row = session.scalar(
                select(QueueMessageModel)
                .where(
                    QueueMessageModel.topic == topic,
                    QueueMessageModel.available_at <= now,
                    (
                        (QueueMessageModel.status == "pending")
                        | (
                            (QueueMessageModel.status == "leased")
                            & (QueueMessageModel.lease_until < now)
                        )
                    ),
                )
                .order_by(QueueMessageModel.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = "leased"
            row.worker_id = worker_id
            row.attempts += 1
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            row.updated_at = now
            session.commit()
            return QueueMessage(row.id, row.topic, row.payload, row.attempts)

    def ack(self, message_id: str, worker_id: str) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            result = session.execute(
                update(QueueMessageModel)
                .where(
                    QueueMessageModel.id == message_id,
                    QueueMessageModel.status == "leased",
                    QueueMessageModel.worker_id == worker_id,
                )
                .values(status="completed", lease_until=None, updated_at=now)
            )
            if result.rowcount != 1:
                raise ValueError("Queue message is not leased by this worker")
            session.commit()

    def fail(self, message_id: str, worker_id: str, error: str, retry_after_seconds: int = 5) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            result = session.execute(
                update(QueueMessageModel)
                .where(
                    QueueMessageModel.id == message_id,
                    QueueMessageModel.status == "leased",
                    QueueMessageModel.worker_id == worker_id,
                )
                .values(
                    status="pending",
                    worker_id=None,
                    lease_until=None,
                    available_at=now + timedelta(seconds=retry_after_seconds),
                    last_error=error,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise ValueError("Queue message is not leased by this worker")
            session.commit()
