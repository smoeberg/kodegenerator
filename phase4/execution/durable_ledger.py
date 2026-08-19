"""Durable SQLAlchemy backend for the P4-01 execution replay ledger.

Implements the same fenced state machine as InMemoryReplayLedger:
EMPTY -> PENDING -> SUCCEEDED/FAILED/ABANDONED, with lease expiry and
fencing tokens preventing stale workers from completing a reclaimed claim.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import DateTime, String, Text, and_, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from infrastructure.persistence.models import Base

from .models import ExecutionResult, ExecutionStatus
from .replay_ledger import ClaimOutcome, ClaimOutcomeKind, LedgerRecord, LedgerStatus

DEFAULT_CLAIM_LEASE_SECONDS = 300


class ExecutionReplayLedgerModel(Base):
    """Durable claim + outcome row keyed by execution_id."""

    __tablename__ = "execution_replay_ledger"

    execution_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    grant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    fencing_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


def _result_to_json(result: ExecutionResult) -> dict[str, Any]:
    return {
        "execution_id": result.execution_id,
        "request_id": result.request_id,
        "authority_policy_id": result.authority_policy_id,
        "authority_policy_version": result.authority_policy_version,
        "agent_identity": result.agent_identity,
        "action": result.action,
        "resource": result.resource,
        "context_packet_id": result.context_packet_id,
        "status": result.status.value,
        "adapter_id": result.adapter_id,
        "output": [list(pair) for pair in result.output],
        "error": result.error,
        "executed_at": result.executed_at,
    }


def _result_from_json(payload: dict[str, Any] | None) -> ExecutionResult | None:
    if not payload:
        return None
    return ExecutionResult(
        execution_id=payload["execution_id"],
        request_id=payload["request_id"],
        authority_policy_id=payload["authority_policy_id"],
        authority_policy_version=payload["authority_policy_version"],
        agent_identity=payload["agent_identity"],
        action=payload["action"],
        resource=payload["resource"],
        context_packet_id=payload["context_packet_id"],
        status=ExecutionStatus(payload["status"]),
        adapter_id=payload["adapter_id"],
        output=tuple(tuple(pair) for pair in payload.get("output") or ()),
        error=payload.get("error"),
        executed_at=payload["executed_at"],
    )


def _to_record(row: ExecutionReplayLedgerModel) -> LedgerRecord:
    return LedgerRecord(
        execution_id=row.execution_id,
        status=LedgerStatus(row.status),
        result=_result_from_json(row.result_json),
        grant_id=row.grant_id,
        request_id=row.request_id,
        lease_expires_at=row.lease_expires_at,
        fencing_token=row.fencing_token,
    )


def _new_token() -> str:
    return secrets.token_urlsafe(16)


def _aware_utc(value: datetime | None = None) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("ledger timestamps must be timezone-aware")
    return instant.astimezone(timezone.utc)


class SqlAlchemyReplayLedger:
    """Crash-safe replay ledger backed by a shared SQLAlchemy session factory."""

    def __init__(self, session_factory: Callable[[], Session], *, claim_lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS) -> None:
        if type(claim_lease_seconds) is not int or claim_lease_seconds < 1:
            raise ValueError("claim_lease_seconds must be a positive int")
        self.session_factory = session_factory
        self.claim_lease_seconds = claim_lease_seconds

    def try_claim(self, execution_id: str, *, grant_id: str | None = None, request_id: str | None = None, now: datetime | None = None) -> ClaimOutcome:
        if not execution_id or not execution_id.strip():
            raise ValueError("execution_id must be non-empty")
        instant = _aware_utc(now)
        lease = instant + timedelta(seconds=self.claim_lease_seconds)
        token = _new_token()

        with self.session_factory() as session:
            row = session.get(ExecutionReplayLedgerModel, execution_id)
            if row is None:
                session.add(ExecutionReplayLedgerModel(
                    execution_id=execution_id,
                    status=LedgerStatus.PENDING.value,
                    grant_id=grant_id,
                    request_id=request_id,
                    result_json=None,
                    started_at=instant,
                    completed_at=None,
                    lease_expires_at=lease,
                    fencing_token=token,
                    error_text=None,
                ))
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    return self._outcome_after_conflict(session, execution_id)
                return ClaimOutcome(ClaimOutcomeKind.ACQUIRED, LedgerRecord(
                    execution_id=execution_id,
                    status=LedgerStatus.PENDING,
                    grant_id=grant_id,
                    request_id=request_id,
                    lease_expires_at=lease,
                    fencing_token=token,
                ))

            if row.status == LedgerStatus.SUCCEEDED.value:
                return ClaimOutcome(ClaimOutcomeKind.ALREADY_SUCCEEDED, _to_record(row))

            if row.status == LedgerStatus.PENDING.value:
                expiry = row.lease_expires_at
                if expiry is not None and _aware_utc(expiry) > instant:
                    return ClaimOutcome(ClaimOutcomeKind.IN_FLIGHT, _to_record(row))
                result = session.execute(
                    update(ExecutionReplayLedgerModel)
                    .where(
                        ExecutionReplayLedgerModel.execution_id == execution_id,
                        ExecutionReplayLedgerModel.status == LedgerStatus.PENDING.value,
                        or_(ExecutionReplayLedgerModel.lease_expires_at.is_(None), ExecutionReplayLedgerModel.lease_expires_at <= instant),
                    )
                    .values(
                        grant_id=grant_id,
                        request_id=request_id,
                        result_json=None,
                        started_at=instant,
                        completed_at=None,
                        lease_expires_at=lease,
                        fencing_token=token,
                        error_text=None,
                    )
                )
                session.commit()
                if result.rowcount == 1:
                    return ClaimOutcome(ClaimOutcomeKind.ACQUIRED, LedgerRecord(execution_id, LedgerStatus.PENDING, None, grant_id, request_id, lease, token))
                return self._outcome_after_conflict(session, execution_id)

            if row.status in {LedgerStatus.FAILED.value, LedgerStatus.ABANDONED.value}:
                result = session.execute(
                    update(ExecutionReplayLedgerModel)
                    .where(ExecutionReplayLedgerModel.execution_id == execution_id, ExecutionReplayLedgerModel.status == row.status)
                    .values(
                        status=LedgerStatus.PENDING.value,
                        grant_id=grant_id,
                        request_id=request_id,
                        result_json=None,
                        started_at=instant,
                        completed_at=None,
                        lease_expires_at=lease,
                        fencing_token=token,
                        error_text=None,
                    )
                )
                session.commit()
                if result.rowcount == 1:
                    return ClaimOutcome(ClaimOutcomeKind.ACQUIRED, LedgerRecord(execution_id, LedgerStatus.PENDING, None, grant_id, request_id, lease, token))
                return self._outcome_after_conflict(session, execution_id)

            raise RuntimeError(f"unknown ledger status {row.status!r}")

    def _outcome_after_conflict(self, session: Session, execution_id: str) -> ClaimOutcome:
        row = session.get(ExecutionReplayLedgerModel, execution_id)
        if row is None:
            raise RuntimeError(f"integrity conflict for {execution_id!r} but row missing")
        if row.status == LedgerStatus.SUCCEEDED.value:
            return ClaimOutcome(ClaimOutcomeKind.ALREADY_SUCCEEDED, _to_record(row))
        return ClaimOutcome(ClaimOutcomeKind.IN_FLIGHT, _to_record(row))

    def _pending(self, session: Session, execution_id: str, fencing_token: str) -> ExecutionReplayLedgerModel:
        row = session.get(ExecutionReplayLedgerModel, execution_id)
        if row is None or row.status != LedgerStatus.PENDING.value:
            raise RuntimeError(f"claim is not pending for {execution_id!r}")
        if not fencing_token or row.fencing_token != fencing_token:
            raise RuntimeError(f"fencing token mismatch for {execution_id!r}")
        return row

    def complete_succeeded(self, execution_id: str, result: ExecutionResult, *, fencing_token: str) -> None:
        if result.status is not ExecutionStatus.SUCCEEDED:
            raise ValueError("complete_succeeded requires SUCCEEDED result")
        with self.session_factory() as session:
            row = self._pending(session, execution_id, fencing_token)
            row.status = LedgerStatus.SUCCEEDED.value
            row.result_json = _result_to_json(result)
            row.completed_at = datetime.now(timezone.utc)
            row.lease_expires_at = None
            row.fencing_token = None
            row.error_text = None
            session.commit()

    def complete_failed(self, execution_id: str, result: ExecutionResult, *, fencing_token: str) -> None:
        if result.status is not ExecutionStatus.FAILED:
            raise ValueError("complete_failed requires FAILED result")
        with self.session_factory() as session:
            row = self._pending(session, execution_id, fencing_token)
            row.status = LedgerStatus.FAILED.value
            row.result_json = _result_to_json(result)
            row.completed_at = datetime.now(timezone.utc)
            row.lease_expires_at = None
            row.fencing_token = None
            row.error_text = result.error
            session.commit()

    def abandon(self, execution_id: str, *, fencing_token: str) -> None:
        with self.session_factory() as session:
            row = session.get(ExecutionReplayLedgerModel, execution_id)
            if row is None or row.status != LedgerStatus.PENDING.value:
                return
            if not fencing_token or row.fencing_token != fencing_token:
                raise RuntimeError(f"fencing token mismatch for {execution_id!r}")
            row.status = LedgerStatus.ABANDONED.value
            row.completed_at = datetime.now(timezone.utc)
            row.result_json = None
            row.lease_expires_at = None
            row.fencing_token = None
            session.commit()

    def get(self, execution_id: str) -> LedgerRecord | None:
        with self.session_factory() as session:
            row = session.get(ExecutionReplayLedgerModel, execution_id)
            return None if row is None else _to_record(row)
