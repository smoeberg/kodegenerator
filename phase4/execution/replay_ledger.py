"""P4-01 execution replay ledger — state machine for single-flight claims.

Invariant: for a given execution_id the adapter may perform at most one
*successful* side-effecting invocation (cluster-wide once a durable backend
is plugged in). Failed attempts do not permanently lock the id.

Pending claims carry a lease and a fencing token. Concurrent claims within
the lease return IN_FLIGHT. After lease expiry a new claim may reclaim the
id (RA-3). complete_*/abandon require the claim's fencing_token so a zombie
worker cannot finish after being reclaimed.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Protocol

from .models import ExecutionResult, ExecutionStatus

DEFAULT_CLAIM_LEASE_SECONDS = 300


class LedgerStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ClaimOutcomeKind(str, Enum):
    ACQUIRED = "acquired"
    ALREADY_SUCCEEDED = "already_succeeded"
    IN_FLIGHT = "in_flight"


class StaleClaimTokenError(RuntimeError):
    """complete/abandon used a fencing token that no longer owns the claim."""


@dataclass(frozen=True)
class LedgerRecord:
    execution_id: str
    status: LedgerStatus
    result: ExecutionResult | None = None
    grant_id: str | None = None
    request_id: str | None = None
    lease_expires_at: datetime | None = None
    fencing_token: str | None = None


@dataclass(frozen=True)
class ClaimOutcome:
    kind: ClaimOutcomeKind
    record: LedgerRecord | None = None


def _aware_utc(value: datetime | None = None) -> datetime:
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        return instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _lease_expired(lease_expires_at: datetime | None, now: datetime) -> bool:
    if lease_expires_at is None:
        return True
    return _aware_utc(now) >= _aware_utc(lease_expires_at)


def _new_fencing_token() -> str:
    return secrets.token_urlsafe(16)


class ExecutionReplayLedger(Protocol):
    def try_claim(
        self,
        execution_id: str,
        *,
        grant_id: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> ClaimOutcome: ...

    def complete_succeeded(
        self,
        execution_id: str,
        result: ExecutionResult,
        *,
        fencing_token: str,
    ) -> None: ...

    def complete_failed(
        self,
        execution_id: str,
        result: ExecutionResult,
        *,
        fencing_token: str,
    ) -> None: ...

    def abandon(self, execution_id: str, *,
 fencing_token: str) -> None: ...

    def get(self, execution_id: str) -> LedgerRecord | None: ...


@dataclass
class InMemoryReplayLedger:
    claim_lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS
    _records: dict[str, LedgerRecord] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def __post_init__(self) -> None:
        if type(self.claim_lease_seconds) is not int or self.claim_lease_seconds < 1:
            raise ValueError("claim_lease_seconds must be a positive int")

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

        with self._lock:
            current = self._records.get(execution_id)

            if current is not None and current.status is LedgerStatus.SUCCEEDED:
                return ClaimOutcome(
                    kind=ClaimOutcomeKind.ALREADY_SUCCEEDED,
                    record=current,
                )

            if current is not None and current.status is LedgerStatus.PENDING:
                if not _lease_expired(current.lease_expires_at, instant):
                    return ClaimOutcome(
                        kind=ClaimOutcomeKind.IN_FLIGHT,
                        record=current,
                    )

            if current is None or current.status in {
                LedgerStatus.FAILED,
                LedgerStatus.PENDING,
            }:
                token = _new_fencing_token()
                record = LedgerRecord(
                    execution_id=execution_id,
                    status=LedgerStatus.PENDING,
                    result=None,
                    grant_id=grant_id,
                    request_id=request_id,
                    lease_expires_at=lease_until,
                    fencing_token=token,
                )
                self._records[execution_id] = record
                return ClaimOutcome(kind=ClaimOutcomeKind.ACQUIRED, record=record)

            raise RuntimeError(f"unknown ledger status {current.status!r}")

    def _require_pending_token(
        self, execution_id: str, fencing_token: str, op: str
    ) -> LedgerRecord:
        if not fencing_token or not fencing_token.strip():
            raise ValueError("fencing_token must be non-empty")
        current = self._records.get(execution_id)
        if current is None or current.status is not LedgerStatus.PENDING:
            raise RuntimeError(f"{op} requires pending claim for {execution_id!r}")
        if current.fencing_token != fencing_token:
            raise StaleClaimTokenError(
                f"{op} fencing token mismatch for {execution_id!r}"
            )
        return current

    def complete_succeeded(
        self,
        execution_id: str,
        result: ExecutionResult,
        *,
        fencing_token: str,
    ) -> None:
        with self._lock:
            current = self._require_pending_token(
                execution_id, fencing_token, "complete_succeeded"
            )
            if result.status is not ExecutionStatus.SUCCEEDED:
                raise ValueError("complete_succeeded requires SUCCEEDED result")
            self._records[execution_id] = replace(
                current,
                status=LedgerStatus.SUCCEEDED,
                result=result,
                lease_expires_at=None,
                fencing_token=None,
            )

    def complete_failed(
        self,
        execution_id: str,
        result: ExecutionResult,
        *,
        fencing_token: str,
    ) -> None:
        with self._lock:
            current = self._require_pending_token(
                execution_id, fencing_token, "complete_failed"
            )
            if result.status is not ExecutionStatus.FAILED:
                raise ValueError("complete_failed requires FAILED result")
            self._records[execution_id] = replace(
                current,
                status=LedgerStatus.FAILED,
                result=result,
                lease_expires_at=None,
                fencing_token=None,
            )

    def abandon(self, execution_id: str, *, fencing_token: str) -> None:
        with self._lock:
            current = self._records.get(execution_id)
            if current is None or current.status is not LedgerStatus.PENDING:
                return
            if not fencing_token or current.fencing_token != fencing_token:
                raise StaleClaimTokenError(
                    f"abandon fencing token mismatch for {execution_id!r}"
                )
            del self._records[execution_id]

    def get(self, execution_id: str) -> LedgerRecord | None:
        with self._lock:
            return self._records.get(execution_id)
