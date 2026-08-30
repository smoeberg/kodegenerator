"""Durable database-backed queue primitives for Phase 7 workers."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Integer, String, Text, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.models import Base


class QueueMessageModel(Base):
    __tablename__ = "runtime_queue_messages"

    organization_id: Mapped[str] = mapped_column(
        String(128), primary_key=True, nullable=False, index=True
    )
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), index=True, nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    lease_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(nullable=False)


@dataclass(frozen=True)
class QueueMessage:
    id: str
    organization_id: str
    topic: str
    payload: dict[str, Any]
    attempts: int
    lease_id: str | None = None


class DatabaseQueue:
    """At-least-once queue with leases, retries and transaction-aware publication."""

    def __init__(
        self,
        session_factory,
        *,
        organization_id: str,
        lease_seconds: int = 60,
        max_attempts: int = 5,
    ):
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        organization_id = organization_id.strip()
        if not organization_id or len(organization_id) > 128:
            raise ValueError("organization_id must contain 1-128 characters")
        self.session_factory = session_factory
        self.organization_id = organization_id
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def enqueue_in_session(
        self,
        session: Session,
        topic: str,
        payload: dict[str, Any],
        message_id: str | None = None,
    ) -> str:
        apply_tenant_context(session, self.organization_id)
        now = datetime.now(timezone.utc)
        message_id = message_id or str(uuid4())
        session.add(QueueMessageModel(
            id=message_id, organization_id=self.organization_id,
            topic=topic, payload=payload, status="pending", attempts=0,
            available_at=now, created_at=now, updated_at=now,
        ))
        return message_id

    def publish(self, topic: str, payload: dict[str, Any], message_id: str | None = None) -> str:
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            message_id = self.enqueue_in_session(session, topic, payload, message_id)
            session.commit()
            return message_id

    def claim(self, topic: str, worker_id: str) -> QueueMessage | None:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            session.execute(
                update(QueueMessageModel)
                .where(
                    QueueMessageModel.topic == topic,
                    QueueMessageModel.organization_id == self.organization_id,
                    QueueMessageModel.attempts >= self.max_attempts,
                    (
                        (QueueMessageModel.status == "pending")
                        | (
                            (QueueMessageModel.status == "leased")
                            & (QueueMessageModel.lease_until < now)
                        )
                    ),
                )
                .values(
                    status="dead_letter",
                    worker_id=None,
                    lease_id=None,
                    lease_until=None,
                    updated_at=now,
                )
            )
            row = session.scalar(
                select(QueueMessageModel)
                .where(
                    QueueMessageModel.topic == topic,
                    QueueMessageModel.organization_id == self.organization_id,
                    QueueMessageModel.available_at <= now,
                    QueueMessageModel.attempts < self.max_attempts,
                    ((QueueMessageModel.status == "pending") | ((QueueMessageModel.status == "leased") & (QueueMessageModel.lease_until < now))),
                )
                .order_by(QueueMessageModel.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                # Persist any exhausted-message dead-letter transitions made
                # before the claim query.
                session.commit()
                return None
            row.status = "leased"
            row.worker_id = worker_id
            row.attempts += 1
            row.lease_id = str(uuid4())
            row.lease_until = now + timedelta(seconds=self.lease_seconds)
            row.updated_at = now
            session.commit()
            return QueueMessage(
                row.id, row.organization_id, row.topic, row.payload,
                row.attempts, row.lease_id,
            )

    def ack(self, message_id: str, worker_id: str, lease_id: str) -> None:
        self._transition(message_id, worker_id, lease_id, "completed", None)

    def fail(
        self,
        message_id: str,
        worker_id: str,
        lease_id: str,
        error: str,
        retry_after_seconds: int = 5,
    ) -> None:
        if retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be non-negative")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            row = session.scalar(
                select(QueueMessageModel)
                .where(
                    QueueMessageModel.id == message_id,
                    QueueMessageModel.organization_id == self.organization_id,
                )
                .with_for_update()
            )
            if (
                row is None
                or row.status != "leased"
                or row.worker_id != worker_id
                or row.lease_id != lease_id
            ):
                raise ValueError("Queue message is not leased by this worker")
            exhausted = row.attempts >= self.max_attempts
            row.status = "dead_letter" if exhausted else "pending"
            row.worker_id = None
            row.lease_id = None
            row.lease_until = None
            if not exhausted:
                row.available_at = now + timedelta(seconds=retry_after_seconds)
            row.last_error = error
            row.updated_at = now
            session.commit()

    def requeue_expired(self, limit: int = 100) -> int:
        """Explicitly recover expired leases; claim() also remains crash-safe."""
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            rows = session.scalars(select(QueueMessageModel).where(
                QueueMessageModel.organization_id == self.organization_id,
                QueueMessageModel.status == "leased",
                QueueMessageModel.lease_until < now,
            ).order_by(QueueMessageModel.updated_at).limit(limit)).all()
            for row in rows:
                row.status = (
                    "dead_letter" if row.attempts >= self.max_attempts else "pending"
                )
                row.worker_id = None
                row.lease_id = None
                row.lease_until = None
                row.available_at = now
                row.updated_at = now
            session.commit()
            return len(rows)

    def dead_letter_count(self, topic: str | None = None) -> int:
        """Return the number of terminally failed queue messages."""
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            query = select(QueueMessageModel).where(
                QueueMessageModel.organization_id == self.organization_id,
                QueueMessageModel.status == "dead_letter"
            )
            if topic is not None:
                query = query.where(QueueMessageModel.topic == topic)
            return len(session.scalars(query).all())

    def _transition(
        self,
        message_id: str,
        worker_id: str,
        lease_id: str,
        status: str,
        error: str | None,
    ) -> None:
        if not lease_id:
            raise ValueError("lease_id must be non-empty")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            result = session.execute(update(QueueMessageModel).where(
                QueueMessageModel.id == message_id,
                QueueMessageModel.organization_id == self.organization_id,
                QueueMessageModel.status == "leased",
                QueueMessageModel.worker_id == worker_id,
                QueueMessageModel.lease_id == lease_id,
            ).values(
                status=status,
                worker_id=None,
                lease_id=None,
                lease_until=None,
                updated_at=now,
                last_error=error,
            ))
            if result.rowcount != 1:
                raise ValueError("Queue message is not leased by this worker")
            session.commit()
