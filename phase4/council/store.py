"""Durable Council aggregate repository with OCC and transactional outbox."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.epistemics.models import Evidence, Hypothesis

from .dispute import DisputeProtocol
from .models import Dispute, DisputeStatus, SessionState, Vote
from .persistence_models import (
    CouncilDisputeModel,
    CouncilEvidenceBindingModel,
    CouncilOutboxEventModel,
    CouncilSessionModel,
    CouncilVoteModel,
)
from .runtime_models import (
    CouncilOutboxEvent,
    CouncilRuntimeEventType,
    CouncilSessionBinding,
    PersistedDeliberation,
)
from .session import DeliberationSession


class CouncilStoreError(RuntimeError):
    """Base durable Council store error."""


class CouncilConflictError(CouncilStoreError):
    """Raised when a state version or immutable evidence binding conflicts."""


class CouncilNotFoundError(CouncilStoreError):
    """Raised when an organization cannot access the requested session."""


class CouncilStore:
    """Persist and rehydrate the complete Council aggregate.

    Writes update the session snapshot, normalized disputes/votes/evidence, and
    outbox events in one database transaction. Every lookup is organization
    scoped, and every update requires the exact observed ``state_version``.
    """

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def create(
        self,
        session: DeliberationSession,
        binding: CouncilSessionBinding,
    ) -> PersistedDeliberation:
        now = datetime.now(timezone.utc)
        with self.session_factory() as db:
            db.add(
                CouncilSessionModel(
                    session_id=session.session_id,
                    organization_id=binding.organization_id,
                    hypothesis_id=session.hypothesis.hypothesis_id,
                    hypothesis_revision=binding.hypothesis_revision,
                    workspace_revision=binding.workspace_revision,
                    context_packet_id=binding.context_packet_id,
                    state=session.state.value,
                    current_round=session.current_round,
                    max_rounds=session.max_rounds,
                    approval_threshold=session.approval_threshold,
                    state_version=0,
                    hypothesis=session.hypothesis.model_dump(mode="json"),
                    history=list(session.history),
                    created_at=now,
                    updated_at=now,
                )
            )
            self._sync_children(db, binding, session)
            self._append_outbox(
                db,
                event_type=CouncilRuntimeEventType.SESSION_CREATED,
                binding=binding,
                session=session,
                state_version=0,
                payload={"state": session.state.value},
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise CouncilConflictError(
                    "council session or immutable child record already exists"
                ) from exc
        return PersistedDeliberation(session, binding, 0)

    def get(
        self,
        organization_id: str,
        session_id: str,
    ) -> PersistedDeliberation | None:
        with self.session_factory() as db:
            row = db.scalar(
                select(CouncilSessionModel).where(
                    CouncilSessionModel.organization_id == organization_id,
                    CouncilSessionModel.session_id == session_id,
                )
            )
            if row is None:
                return None
            binding = self._binding(row)
            return PersistedDeliberation(
                session=self._rehydrate(db, row),
                binding=binding,
                state_version=row.state_version,
            )

    def save(
        self,
        organization_id: str,
        session: DeliberationSession,
        *,
        expected_version: int,
    ) -> int:
        now = datetime.now(timezone.utc)
        with self.session_factory() as db:
            row = db.scalar(
                select(CouncilSessionModel).where(
                    CouncilSessionModel.organization_id == organization_id,
                    CouncilSessionModel.session_id == session.session_id,
                )
            )
            if row is None:
                raise CouncilNotFoundError("council session not found")
            binding = self._binding(row)
            self._verify_immutable_session_fields(row, session)

            previous_state = SessionState(row.state)
            next_version = expected_version + 1
            result = db.execute(
                update(CouncilSessionModel)
                .where(
                    CouncilSessionModel.organization_id == organization_id,
                    CouncilSessionModel.session_id == session.session_id,
                    CouncilSessionModel.state_version == expected_version,
                )
                .values(
                    state=session.state.value,
                    current_round=session.current_round,
                    state_version=next_version,
                    hypothesis=session.hypothesis.model_dump(mode="json"),
                    history=list(session.history),
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                db.rollback()
                raise CouncilConflictError(
                    f"stale council state version: expected {expected_version}"
                )

            self._sync_children(db, binding, session)
            if (
                session.state is SessionState.DEADLOCKED
                and previous_state is not SessionState.DEADLOCKED
            ):
                self._append_outbox(
                    db,
                    event_type=CouncilRuntimeEventType.HUMAN_REQUIRED,
                    binding=binding,
                    session=session,
                    state_version=next_version,
                    payload={
                        "reason": "maximum deliberation rounds exhausted",
                        "current_round": session.current_round,
                    },
                )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise CouncilConflictError(
                    "concurrent or immutable council child record conflict"
                ) from exc
            return next_version

    def evidence_revision_map(
        self,
        organization_id: str,
        session_id: str,
    ) -> dict[str, str]:
        """Return repository-derived evidence revisions for Authority readiness."""
        with self.session_factory() as db:
            rows = db.scalars(
                select(CouncilEvidenceBindingModel).where(
                    CouncilEvidenceBindingModel.organization_id == organization_id,
                    CouncilEvidenceBindingModel.session_id == session_id,
                )
            ).all()
            return {row.evidence_id: row.workspace_revision for row in rows}

    def pending_events(
        self,
        organization_id: str,
        *,
        limit: int = 100,
    ) -> tuple[CouncilOutboxEvent, ...]:
        with self.session_factory() as db:
            rows = db.scalars(
                select(CouncilOutboxEventModel)
                .where(
                    CouncilOutboxEventModel.organization_id == organization_id,
                    CouncilOutboxEventModel.status == "pending",
                )
                .order_by(CouncilOutboxEventModel.created_at)
                .limit(limit)
            ).all()
            return tuple(
                CouncilOutboxEvent(
                    event_id=row.event_id,
                    organization_id=row.organization_id,
                    event_type=CouncilRuntimeEventType(row.event_type),
                    aggregate_id=row.aggregate_id,
                    payload=row.payload,
                    correlation_id=row.correlation_id,
                    created_at=row.created_at,
                )
                for row in rows
            )

    def mark_published(self, organization_id: str, event_id: str) -> None:
        with self.session_factory() as db:
            result = db.execute(
                update(CouncilOutboxEventModel)
                .where(
                    CouncilOutboxEventModel.organization_id == organization_id,
                    CouncilOutboxEventModel.event_id == event_id,
                    CouncilOutboxEventModel.status == "pending",
                )
                .values(status="published", published_at=datetime.now(timezone.utc))
            )
            if result.rowcount != 1:
                raise CouncilNotFoundError("pending council outbox event not found")
            db.commit()

    def _sync_children(
        self,
        db: Session,
        binding: CouncilSessionBinding,
        session: DeliberationSession,
    ) -> None:
        self._sync_disputes(db, binding, session)
        self._sync_votes(db, binding, session)
        self._sync_evidence(db, binding, session)

    def _sync_disputes(
        self,
        db: Session,
        binding: CouncilSessionBinding,
        session: DeliberationSession,
    ) -> None:
        existing = {
            row.dispute_id: row
            for row in db.scalars(
                select(CouncilDisputeModel).where(
                    CouncilDisputeModel.organization_id == binding.organization_id,
                    CouncilDisputeModel.session_id == session.session_id,
                )
            ).all()
        }
        for dispute in session.dispute_protocol._disputes.values():
            payload = dispute.model_dump(mode="json")
            row = existing.get(dispute.dispute_id)
            if row is None:
                db.add(
                    CouncilDisputeModel(
                        dispute_id=dispute.dispute_id,
                        organization_id=binding.organization_id,
                        session_id=session.session_id,
                        hypothesis_id=dispute.hypothesis_id,
                        status=dispute.status.value,
                        payload=payload,
                        created_at=dispute.created_at,
                        updated_at=dispute.resolved_at or dispute.created_at,
                    )
                )
            else:
                persisted = Dispute.model_validate(row.payload)
                if (
                    dispute.hypothesis_id != persisted.hypothesis_id
                    or dispute.raised_by_agent_id != persisted.raised_by_agent_id
                    or dispute.reason != persisted.reason
                    or dispute.created_at != persisted.created_at
                ):
                    raise CouncilConflictError(
                        "immutable dispute identity changed after persistence"
                    )
                if (
                    persisted.status is not dispute.status
                    and persisted.status is not DisputeStatus.OPEN
                ):
                    raise CouncilConflictError(
                        "terminal dispute state cannot be changed"
                    )
                row.status = dispute.status.value
                row.payload = payload
                row.updated_at = dispute.resolved_at or datetime.now(timezone.utc)

    def _sync_votes(
        self,
        db: Session,
        binding: CouncilSessionBinding,
        session: DeliberationSession,
    ) -> None:
        existing = {
            row.vote_id: row
            for row in db.scalars(
                select(CouncilVoteModel).where(
                    CouncilVoteModel.organization_id == binding.organization_id,
                    CouncilVoteModel.session_id == session.session_id,
                )
            ).all()
        }
        for round_number, votes in session.votes.items():
            for vote in votes:
                vote_id = self._digest(
                    binding.organization_id,
                    session.session_id,
                    str(round_number),
                    vote.agent_id,
                )
                persisted = existing.get(vote_id)
                if persisted is not None:
                    if persisted.payload != vote.model_dump(mode="json"):
                        raise CouncilConflictError(
                            "persisted council vote cannot be changed"
                        )
                    continue
                db.add(
                    CouncilVoteModel(
                        vote_id=vote_id,
                        organization_id=binding.organization_id,
                        session_id=session.session_id,
                        round_number=round_number,
                        agent_id=vote.agent_id,
                        hypothesis_id=vote.hypothesis_id,
                        approved=vote.approved,
                        payload=vote.model_dump(mode="json"),
                        created_at=vote.timestamp,
                    )
                )

    def _sync_evidence(
        self,
        db: Session,
        binding: CouncilSessionBinding,
        session: DeliberationSession,
    ) -> None:
        existing = {
            row.evidence_id: row
            for row in db.scalars(
                select(CouncilEvidenceBindingModel).where(
                    CouncilEvidenceBindingModel.organization_id
                    == binding.organization_id,
                    CouncilEvidenceBindingModel.session_id == session.session_id,
                )
            ).all()
        }
        for evidence in self._all_evidence(session):
            content_digest = self._json_digest(evidence.model_dump(mode="json"))
            row = existing.get(evidence.evidence_id)
            if row is not None:
                if (
                    row.content_digest != content_digest
                    or row.hypothesis_revision != binding.hypothesis_revision
                    or row.workspace_revision != binding.workspace_revision
                ):
                    raise CouncilConflictError(
                        "immutable evidence binding changed after persistence"
                    )
                continue
            db.add(
                CouncilEvidenceBindingModel(
                    binding_id=self._digest(
                        binding.organization_id,
                        session.session_id,
                        evidence.evidence_id,
                    ),
                    evidence_id=evidence.evidence_id,
                    organization_id=binding.organization_id,
                    session_id=session.session_id,
                    hypothesis_id=evidence.hypothesis_id,
                    hypothesis_revision=binding.hypothesis_revision,
                    workspace_revision=binding.workspace_revision,
                    context_packet_id=binding.context_packet_id,
                    source=evidence.source,
                    content_digest=content_digest,
                    created_at=evidence.timestamp,
                )
            )

    @staticmethod
    def _all_evidence(session: DeliberationSession) -> Iterable[Evidence]:
        seen: set[str] = set()
        candidates = list(session.hypothesis.supporting_evidence)
        candidates.extend(session.hypothesis.contradicting_evidence)
        candidates.extend(
            dispute.resolving_evidence
            for dispute in session.dispute_protocol._disputes.values()
            if dispute.resolving_evidence is not None
        )
        for evidence in candidates:
            if evidence.evidence_id not in seen:
                seen.add(evidence.evidence_id)
                yield evidence

    def _rehydrate(
        self,
        db: Session,
        row: CouncilSessionModel,
    ) -> DeliberationSession:
        protocol = DisputeProtocol()
        dispute_rows = db.scalars(
            select(CouncilDisputeModel).where(
                CouncilDisputeModel.organization_id == row.organization_id,
                CouncilDisputeModel.session_id == row.session_id,
            )
        ).all()
        protocol._disputes = {
            dispute_row.dispute_id: Dispute.model_validate(dispute_row.payload)
            for dispute_row in dispute_rows
        }
        session = DeliberationSession(
            hypothesis=Hypothesis.model_validate(row.hypothesis),
            max_rounds=row.max_rounds,
            approval_threshold=row.approval_threshold,
            dispute_protocol=protocol,
            session_id=row.session_id,
        )
        session.current_round = row.current_round
        session.state = SessionState(row.state)
        session.history = list(row.history)
        session.votes = {}
        vote_rows = db.scalars(
            select(CouncilVoteModel)
            .where(
                CouncilVoteModel.organization_id == row.organization_id,
                CouncilVoteModel.session_id == row.session_id,
            )
            .order_by(CouncilVoteModel.round_number, CouncilVoteModel.created_at)
        ).all()
        for vote_row in vote_rows:
            session.votes.setdefault(vote_row.round_number, []).append(
                Vote.model_validate(vote_row.payload)
            )
        session.votes.setdefault(session.current_round, [])
        return session

    @staticmethod
    def _binding(row: CouncilSessionModel) -> CouncilSessionBinding:
        return CouncilSessionBinding(
            organization_id=row.organization_id,
            context_packet_id=row.context_packet_id,
            hypothesis_revision=row.hypothesis_revision,
            workspace_revision=row.workspace_revision,
        )

    @staticmethod
    def _verify_immutable_session_fields(
        row: CouncilSessionModel,
        session: DeliberationSession,
    ) -> None:
        persisted = Hypothesis.model_validate(row.hypothesis)
        if (
            session.hypothesis.hypothesis_id != row.hypothesis_id
            or session.hypothesis.task_id != persisted.task_id
            or session.hypothesis.statement != persisted.statement
            or session.hypothesis.created_at != persisted.created_at
        ):
            raise CouncilConflictError("session hypothesis binding cannot change")
        if (
            session.max_rounds != row.max_rounds
            or session.approval_threshold != row.approval_threshold
        ):
            raise CouncilConflictError("session deliberation policy cannot change")

    def _append_outbox(
        self,
        db: Session,
        *,
        event_type: CouncilRuntimeEventType,
        binding: CouncilSessionBinding,
        session: DeliberationSession,
        state_version: int,
        payload: dict[str, object],
    ) -> None:
        event_id = self._digest(
            event_type.value,
            binding.organization_id,
            session.session_id,
            str(state_version),
        )
        if db.get(CouncilOutboxEventModel, event_id) is not None:
            return
        event_payload = {
            "session_id": session.session_id,
            "hypothesis_id": session.hypothesis.hypothesis_id,
            "hypothesis_revision": binding.hypothesis_revision,
            "workspace_revision": binding.workspace_revision,
            "context_packet_id": binding.context_packet_id,
            "state_version": state_version,
            **payload,
        }
        db.add(
            CouncilOutboxEventModel(
                event_id=event_id,
                organization_id=binding.organization_id,
                event_type=event_type.value,
                aggregate_id=session.session_id,
                payload=event_payload,
                correlation_id=session.session_id,
                status="pending",
                created_at=datetime.now(timezone.utc),
                published_at=None,
            )
        )

    @staticmethod
    def _digest(*parts: str) -> str:
        return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()

    @staticmethod
    def _json_digest(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
