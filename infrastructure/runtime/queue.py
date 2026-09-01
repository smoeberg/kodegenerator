"""Durable database-backed queue primitives for Phase 7 workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, Integer, String, Text, select, update
from sqlalchemy.exc import IntegrityError
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
    status: Mapped[str] = mapped_column(
        String(32), index=True, nullable=False, default="pending"
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(nullable=False)
    lease_until: Mapped[datetime | None] = mapped_column(nullable=True)
    lease_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    worker_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
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
    status: str = "pending"
    lease_until: datetime | None = None
    worker_id: str | None = None
    last_error: str | None = None


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
        session.add(
            QueueMessageModel(
                id=message_id,
                organization_id=self.organization_id,
                topic=topic,
                payload=payload,
                status="pending",
                attempts=0,
                available_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        return message_id

    def publish(
        self, topic: str, payload: dict[str, Any], message_id: str | None = None
    ) -> str:
        try:
            with self.session_factory() as session:
                apply_tenant_context(session, self.organization_id)
                message_id = self.enqueue_in_session(
                    session, topic, payload, message_id
                )
                session.commit()
                return message_id
        except IntegrityError:
            if message_id is None:
                raise
            existing = self.get(message_id)
            if (
                existing is None
                or existing.topic != topic
                or existing.payload != payload
            ):
                raise ValueError("queue message ID conflicts with existing payload")
            return message_id

    def claim(
        self,
        topic: str,
        worker_id: str,
        *,
        eligible: Callable[[dict[str, Any]], bool] | None = None,
        order_key: Callable[[dict[str, Any]], Any] | None = None,
    ) -> QueueMessage | None:
        if not worker_id.strip():
            raise ValueError("worker_id must be non-empty")
        now = datetime.now(timezone.utc)
        # A select followed by an ORM mutation is not a claim boundary on
        # SQLite, where FOR UPDATE is ignored. Compare-and-set the selected
        # version so every supported database elects exactly one claimant.
        for _ in range(100):
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
                rows = session.scalars(
                    select(QueueMessageModel)
                    .where(
                        QueueMessageModel.topic == topic,
                        QueueMessageModel.organization_id == self.organization_id,
                        QueueMessageModel.available_at <= now,
                        QueueMessageModel.attempts < self.max_attempts,
                        (
                            (QueueMessageModel.status == "pending")
                            | (
                                (QueueMessageModel.status == "leased")
                                & (QueueMessageModel.lease_until < now)
                            )
                        ),
                    )
                    .order_by(QueueMessageModel.created_at, QueueMessageModel.id)
                ).all()
                candidates = [
                    candidate
                    for candidate in rows
                    if eligible is None or eligible(dict(candidate.payload))
                ]
                if order_key is not None:
                    candidates.sort(
                        key=lambda candidate: order_key(dict(candidate.payload))
                    )
                row = candidates[0] if candidates else None
                if row is None:
                    session.commit()
                    return None
                lease_id = str(uuid4())
                previous_status = row.status
                previous_lease_id = row.lease_id
                previous_attempts = row.attempts
                claim = session.execute(
                    update(QueueMessageModel)
                    .where(
                        QueueMessageModel.organization_id == self.organization_id,
                        QueueMessageModel.id == row.id,
                        QueueMessageModel.status == previous_status,
                        QueueMessageModel.attempts == previous_attempts,
                        QueueMessageModel.lease_id == previous_lease_id
                        if previous_lease_id is not None
                        else QueueMessageModel.lease_id.is_(None),
                    )
                    .values(
                        status="leased",
                        worker_id=worker_id,
                        attempts=previous_attempts + 1,
                        lease_id=lease_id,
                        lease_until=now + timedelta(seconds=self.lease_seconds),
                        updated_at=now,
                    )
                )
                if claim.rowcount == 1:
                    payload = dict(row.payload)
                    message_id = row.id
                    organization_id = row.organization_id
                    session.commit()
                    return QueueMessage(
                        message_id,
                        organization_id,
                        topic,
                        payload,
                        previous_attempts + 1,
                        lease_id,
                        "leased",
                        now + timedelta(seconds=self.lease_seconds),
                        worker_id,
                    )
                session.rollback()
        raise RuntimeError("queue claim contention exceeded retry limit")

    def heartbeat(self, message_id: str, worker_id: str, lease_id: str) -> None:
        if not lease_id:
            raise ValueError("lease_id must be non-empty")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            result = session.execute(
                update(QueueMessageModel)
                .where(
                    QueueMessageModel.id == message_id,
                    QueueMessageModel.organization_id == self.organization_id,
                    QueueMessageModel.status == "leased",
                    QueueMessageModel.worker_id == worker_id,
                    QueueMessageModel.lease_id == lease_id,
                    QueueMessageModel.lease_until >= now,
                )
                .values(
                    lease_until=now + timedelta(seconds=self.lease_seconds),
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                raise ValueError("Queue message is not actively leased by this worker")
            session.commit()

    def ack(
        self,
        message_id: str,
        worker_id: str,
        lease_id: str,
        result: dict[str, Any] | None = None,
    ) -> None:
        self._transition(
            message_id, worker_id, lease_id, "completed", None, result=result
        )

    def fail(
        self,
        message_id: str,
        worker_id: str,
        lease_id: str,
        error: str,
        retry_after_seconds: int = 5,
        *,
        retry: bool = True,
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
            exhausted = not retry or row.attempts >= self.max_attempts
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
            rows = session.scalars(
                select(QueueMessageModel)
                .where(
                    QueueMessageModel.organization_id == self.organization_id,
                    QueueMessageModel.status == "leased",
                    QueueMessageModel.lease_until < now,
                )
                .order_by(QueueMessageModel.updated_at)
                .limit(limit)
            ).all()
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
                QueueMessageModel.status == "dead_letter",
            )
            if topic is not None:
                query = query.where(QueueMessageModel.topic == topic)
            return len(session.scalars(query).all())

    def get(self, message_id: str) -> QueueMessage | None:
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            row = session.get(QueueMessageModel, (self.organization_id, message_id))
            return self._message(row) if row is not None else None

    def list(self, topic: str | None = None) -> list[QueueMessage]:
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            query = select(QueueMessageModel).where(
                QueueMessageModel.organization_id == self.organization_id
            )
            if topic is not None:
                query = query.where(QueueMessageModel.topic == topic)
            rows = session.scalars(query.order_by(QueueMessageModel.created_at)).all()
            return [self._message(row) for row in rows]

    def pending_count(self, topic: str | None = None) -> int:
        return sum(message.status == "pending" for message in self.list(topic))

    def _transition(
        self,
        message_id: str,
        worker_id: str,
        lease_id: str,
        status: str,
        error: str | None,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        if not lease_id:
            raise ValueError("lease_id must be non-empty")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            apply_tenant_context(session, self.organization_id)
            values: dict[str, Any] = {
                "status": status,
                "lease_id": None,
                "lease_until": None,
                "updated_at": now,
                "last_error": error,
            }
            if result is not None:
                row = session.get(QueueMessageModel, (self.organization_id, message_id))
                if row is None:
                    raise ValueError("Queue message is unavailable")
                values["payload"] = {
                    **dict(row.payload),
                    "completion_result": result,
                }
            transition = session.execute(
                update(QueueMessageModel)
                .where(
                    QueueMessageModel.id == message_id,
                    QueueMessageModel.organization_id == self.organization_id,
                    QueueMessageModel.status == "leased",
                    QueueMessageModel.worker_id == worker_id,
                    QueueMessageModel.lease_id == lease_id,
                )
                .values(**values)
            )
            if transition.rowcount != 1:
                raise ValueError("Queue message is not leased by this worker")
            session.commit()

    @staticmethod
    def _message(row: QueueMessageModel) -> QueueMessage:
        return QueueMessage(
            id=row.id,
            organization_id=row.organization_id,
            topic=row.topic,
            payload=dict(row.payload),
            attempts=row.attempts,
            lease_id=row.lease_id,
            status=row.status,
            lease_until=row.lease_until,
            worker_id=row.worker_id,
            last_error=row.last_error,
        )
