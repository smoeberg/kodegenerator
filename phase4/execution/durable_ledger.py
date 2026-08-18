"""Durable SQLAlchemy backend for the P4-01 execution replay ledger."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import DateTime, String, Text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column
from sqlalchemy.types import JSON

from infrastructure.persistence.models import Base

from .models import ExecutionResult, ExecutionStatus
from .replay_ledger import (
    DEFAULT_CLAIM_LEASE_SECONDS,
    ClaimOutcome,
    ClaimOutcomeKind,
    LedgerRecord,
    LedgerStatus,
    StaleClaimTokenError,
    _aware_utc,
    _lease_expired,
    _new_fencing_token,
)


class ExecutionReplayLedgerModel(Base):
    __tablename__ = "execution_replay_ledger"

    execution_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    grant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
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


class SqlAlchemyReplayLedger:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        claim_lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS,
    ) -> None:
        if type(claim_lease_seconds) is not int or claim_lease_seconds < 1:
            raise ValueError("claim_lease_seconds must be a positive int")
        self.session_factory = session_factory
        self.claim_lease_seconds = claim_lease_seconds

    def try_claim(
        self,
        execution_id: str,
        *,
        grant_id: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> ClaimOutcome:
        if not execution_id or not execution_id.strip():
            raise ValueError("execution_id must be non-empty")
        instant = _aware_utc(now)
        lease_until = instant + timedelta(seconds=self.claim_lease_seconds)
        token = _new_fencing_token()

        with self.session_factory() as session:
            row = session.get(ExecutionReplayLedgerModel, execution_id)
            if row is None:
                session.add(
                    ExecutionReplayLedgerModel(
                        execution_id=execution_id,
                        status=LedgerStatus.PENDING.value,
                        grant_id=grant_id,
                        request_id=request_id,
                        result_json=None,
                        started_at=instant,
                        completed_at=None,
                        lease_expires_at=lease_until,
                        fencing_token=token,
                        error_text=None,
                    )
                )
                try:
                    session.commit()
                except IntegrityError:
                    session.rollback()
                    return self._outcome_after_conflict(
                        session, execution_id, instant, grant_id, request_id, lease_until
                    )
                return ClaimOutcome(
                    kind=ClaimOutcomeKind.ACQUIRED,
                    record=LedgerRecord(
                        execution_id=execution_id,
                        status=LedgerStatus.PENDING,
                        grant_id=grant_id,
                        request_id=request_id,
                        lease_expires_at=lease_until,
                        fencing_token=token,
                    ),
                )

            if row.status == LedgerStatus.SUCCEEDED.value:
                return ClaimOutcome(
                    kind=ClaimOutcomeKind.ALREADY_SUCCEEDED,
                    record=_to_record(row),
                )

            if row.status == LedgerStatus.PENDING.value:
                if not _lease_expired(row.lease_expires_at, instant):
                    return ClaimOutcome(
                        kind=ClaimOutcomeKind.IN_FLIGHT,
                        record=_to_record(row),
                    )
                return self._reclaim_pending(
                    session,
                    row,
                    grant_id=grant_id,
                    request_id=request_id,
                    instant=instant,
                    lease_until=lease_until,
                    fencing_token=token,
                )

            if row.status == LedgerStatus.FAILED.value:
                return self._reclaim_failed(
                    session,
                    execution_id,
                    grant_id=grant_id,
                    request_id=request_id,
                    instant=instant,
                    lease_until=lease_until,
                    fencing_token=token,
                )

            raise RuntimeError(f"unknown ledger status {row.status!r}")

    def _reclaim_pending(
        self,
        session: Session,
        row: ExecutionReplayLedgerModel,
        *,
        grant_id: str | None,
        request_id: str | None,
        instant: datetime,
        lease_until: datetime,
        fencing_token: str,
    ) -> ClaimOutcome:
        result = session.execute(
            update(ExecutionReplayLedgerModel)
            .where(
                ExecutionReplayLedgerModel.execution_id == row.execution_id,
                ExecutionReplayLedgerModel.status == LedgerStatus.PENDING.value,
            )
            .values(
                grant_id=grant_id,
                request_id=request_id,
                result_json=None,
                started_at=instant,
                completed_at=None,
                lease_expires_at=lease_until,
                fencing_token=fencing_token,
                error_text=None,
            )
        )
        session.commit()
        if result.rowcount != 1:
            refreshed = session.get(ExecutionReplayLedgerModel, row.execution_id)
            if refreshed is None:
                raise RuntimeError(f"pending reclaim lost row for {row.execution_id!r}")
            if refreshed.status == LedgerStatus.SUCCEEDED.value:
                return ClaimOutcome(
                    kind=ClaimOutcomeKind.ALREADY_SUCCEEDED,
                    record=_to_record(refreshed),
                )
            return ClaimOutcome(
                kind=ClaimOutcomeKind.IN_FLIGHT,
                record=_to_record(refreshed),
            )
        return ClaimOutcome(
            kind=ClaimOutcomeKind.ACQUIRED,
            record=LedgerRecord(
                execution_id=row.execution_id,
                status=LedgerStatus.PENDING,
                grant_id=grant_id,
                request_id=request_id,
                lease_expires_at=lease_until,
                fencing_token=fencing_token,
            ),
        )

    def _reclaim_failed(
        self,
        session: Session,
        execution_id: str,
        *,
        grant_id: str | None,
        request_id: str | None,
        instant: datetime,
        lease_until: datetime,
        fencing_token: str,
    ) -> ClaimOutcome:
        result = session.execute(
            update(ExecutionReplayLedgerModel)
            .where(
                ExecutionReplayLedgerModel.execution_id == execution_id,
                ExecutionReplayLedgerModel.status == LedgerStatus.FAILED.value,
            )
            .values(
                status=LedgerStatus.PENDING.value,
                grant_id=grant_id,
                request_id=request_id,
                result_json=None,
                started_at=instant,
                completed_at=None,
                lease_expires_at=lease_until,
                fencing_token=fencing_token,
                error_text=None,
            )
        )
        session.commit()
        if result.rowcount != 1:
            refreshed = session.get(ExecutionReplayLedgerModel, execution_id)
            if refreshed is None:
                raise RuntimeError(f"failed reclaim lost row for {execution_id!r}")
            if refreshed.status == LedgerStatus.SUCCEEDED.value:
                return ClaimOutcome(
                    kind=ClaimOutcomeKind.ALREADY_SUCCEEDED,
                    record=_to_record(refreshed),
                )
            return ClaimOutcome(
                kind=ClaimOutcomeKind.IN_FLIGHT,
                record=_to_record(refreshed),
            )
        return ClaimOutcome(
            kind=ClaimOutcomeKind.ACQUIRED,
            record=LedgerRecord(
                execution_id=execution_id,
                status=LedgerStatus.PENDING,
                grant_id=grant_id,
                request_id=request_id,
                lease_expires_at=lease_until,
                fencing_token=fencing_token,
            ),
        )

    def _outcome_after_conflict(
        self,
        session: Session,
        execution_id: str,
        instant: datetime,
        grant_id: str | None,
        request_id: str | None,
        lease_until: datetime,
    ) -> ClaimOutcome:
        row = session.get(ExecutionReplayLedgerModel, execution_id)
        if row is None:
            raise RuntimeError(f"integrity conflict for {execution_id!r} but row missing")
        if row.status == LedgerStatus.SUCCEEDED.value:
            return ClaimOutcome(
                kind=ClaimOutcomeKind.ALREADY_SUCCEEDED,
                record=_to_record(row),
            )
        if row.status == LedgerStatus.PENDING.value:
            if _lease_expired(row.lease_expires_at, instant):
                return self._reclaim_pending(
                    session,
                    row,
                    grant_id=grant_id,
                    request_id=request_id,
                    instant=instant,
                    lease_until=lease_until,
                    fencing_token=_new_fencing_token(),
                )
            return ClaimOutcome(
                kind=ClaimOutcomeKind.IN_FLIGHT,
                record=_to_record(row),
            )
        if row.status == LedgerStatus.FAILED.value:
            return self._reclaim_failed(
                session,
                execution_id,
                grant_id=grant_id,
                request_id=request_id,
                instant=instant,
                lease_until=lease_until,
                fencing_token=_new_fencing_token(),
            )
        return ClaimOutcome(
            kind=ClaimOutcomeKind.IN_FLIGHT,
            record=_to_record(row),
        )

    def complete_succeeded(
        self,
        execution_id: str,
        result: ExecutionResult,
        *,
        fencing_token: str,
    ) -> None:
        if result.status is not ExecutionStatus.SUCCEEDED:
            raise ValueError("complete_succeeded requires SUCCEEDED result")
        if not fencing_token or not fencing_token.strip():
            raise ValueError("fencing_token must be non-empty")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            upd = session.execute(
                update(ExecutionReplayLedgerModel)
                .where(
                    ExecutionReplayLedgerModel.execution_id == execution_id,
                    ExecutionReplayLedgerModel.status == LedgerStatus.PENDING.value,
                    ExecutionReplayLedgerModel.fencing_token == fencing_token,
                )
                .values(
                    status=LedgerStatus.SUCCEEDED.value,
                    result_json=_result_to_json(result),
                    completed_at=now,
                    lease_expires_at=None,
                    fencing_token=None,
                    error_text=None,
                )
            )
            session.commit()
            if upd.rowcount != 1:
                raise StaleClaimTokenError(
                    f"complete_succeeded fencing token mismatch for {execution_id!r}"
                )

    def complete_failed(
        self,
        execution_id: str,
        result: ExecutionResult,
        *,
        fencing_token: str,
    ) -> None:
        if result.status is not ExecutionStatus.FAILED:
            raise ValueError("complete_failed requires FAILED result")
        if not fencing_token or not fencing_token.strip():
            raise ValueError("fencing_token must be non-empty")
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            upd = session.execute(
                update(ExecutionReplayLedgerModel)
                .where(
                    ExecutionReplayLedgerModel.execution_id == execution_id,
                    ExecutionReplayLedgerModel.status == LedgerStatus.PENDING.value,
                    ExecutionReplayLedgerModel.fencing_token == fencing_token,
                )
                .values(
                    status=LedgerStatus.FAILED.value,
                    result_json=_result_to_json(result),
                    completed_at=now,
                    lease_expires_at=None,
                    fencing_token=None,
                    error_text=result.error,
                )
            )
            session.commit()
            if upd.rowcount != 1:
                raise StaleClaimTokenError(
                    f"complete_failed fencing token mismatch for {execution_id!r}"
                )

    def abandon(self, execution_id: str, *, fencing_token: str) -> None:
        if not fencing_token or not fencing_token.strip():
            raise ValueError("fencing_token must be non-empty")
        with self.session_factory() as session:
            row = session.get(ExecutionReplayLedgerModel, execution_id)
            if row is None or row.status != LedgerStatus.PENDING.value:
                return
            if row.fencing_token != fencing_token:
                raise StaleClaimTokenError(
                    f"abandon fencing token mismatch for {execution_id!r}"
                )
            session.delete(row)
            session.commit()

    def get(self, execution_id: str) -> LedgerRecord | None:
        with self.session_factory() as session:
            row = session.get(ExecutionReplayLedgerModel, execution_id)
            if row is None:
                return None
            return _to_record(row)
