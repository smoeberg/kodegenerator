"""Transactional persistence boundary for the Phase 4 Brain."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from phase4.contracts import Evidence, KnowledgeRecord, KnowledgeState

from .models import KnowledgeRecordModel, KnowledgeStateModel


class KnowledgeConflictError(RuntimeError):
    """Raised when a writer's observed knowledge version is stale."""


class KnowledgeStore:
    """Persist epistemic records and materialize knowledge with OCC.

    The caller supplies the same SQLAlchemy session factory used by the rest
    of EIRA. Each write is one transaction: record insertion and materialized
    state transition either both commit or neither does.
    """

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def append_and_materialize(self, record: KnowledgeRecord) -> int:
        """Append a record and atomically advance its subject state.

        ``record.version`` is the version observed by the writer. For a new
        subject it must be zero. For an existing subject, exactly that version
        must still be current; otherwise the transaction fails with a conflict.
        """
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            current = session.get(KnowledgeStateModel, record.subject)
            current_version = current.version if current is not None else 0
            if record.version != current_version:
                raise KnowledgeConflictError(
                    f"stale knowledge version for {record.subject!r}: "
                    f"expected {record.version}, current {current_version}"
                )

            session.add(
                KnowledgeRecordModel(
                    record_id=record.record_id,
                    subject=record.subject,
                    claim=record.claim,
                    evidence=[self._evidence_dict(item) for item in record.evidence],
                    state=record.state.value,
                    observed_version=record.version,
                    author_agent_id=record.author_agent_id,
                    created_at=now,
                )
            )

            next_version = current_version + 1
            if current is None:
                session.add(
                    KnowledgeStateModel(
                        subject=record.subject,
                        state=record.state.value,
                        claim=record.claim,
                        evidence=[self._evidence_dict(item) for item in record.evidence],
                        version=next_version,
                        updated_at=now,
                    )
                )
            else:
                result = session.execute(
                    update(KnowledgeStateModel)
                    .where(
                        KnowledgeStateModel.subject == record.subject,
                        KnowledgeStateModel.version == record.version,
                    )
                    .values(
                        state=record.state.value,
                        claim=record.claim,
                        evidence=[self._evidence_dict(item) for item in record.evidence],
                        version=next_version,
                        updated_at=now,
                    )
                )
                if result.rowcount != 1:
                    raise KnowledgeConflictError(
                        f"knowledge state changed while writing {record.subject!r}"
                    )

            session.commit()
            return next_version

    def get_state(self, subject: str) -> KnowledgeStateModel | None:
        with self.session_factory() as session:
            return session.scalar(
                select(KnowledgeStateModel).where(KnowledgeStateModel.subject == subject)
            )

    @staticmethod
    def _evidence_dict(evidence: Evidence) -> dict[str, object]:
        return {
            "evidence_id": evidence.evidence_id,
            "source": evidence.source,
            "content_digest": evidence.content_digest,
            "supports": evidence.supports,
        }
