"""P4-01 execution replay ledger — state machine for single-flight claims.

Invariant: for a given execution_id the adapter may perform at most one
*successful* side-effecting invocation (cluster-wide once a durable backend
is plugged in). Failed attempts do not permanently lock the id.

Pending claims carry a lease. Concurrent claims within the lease return
IN_FLIGHT (fail-closed). After lease expiry a new claim may reclaim the id
(RA-3: crash-under-adapter recovery).

State machine::

    (empty) ──claim──► pending(lease) ──complete(succeeded)──► succeeded
                           │
                           ├──complete(failed)──► failed   (retryable)
                           ├──abandon───────────► (empty)  (retryable)
                           ├──claim within lease─► IN_FLIGHT
                           └──claim after lease──► pending (reclaim)

    succeeded ──claim──► ALREADY_SUCCEEDED
    failed    ──claim──► pending (reclaim)
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Protocol

from .models import ExecutionResult, ExecutionStatus

# Default single-flight lease; expired PENDING may be reclaimed (RA-3).
DEFAULT_CLAIM_LEASE_SECONDS = 300


class LedgerStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ClaimOutcomeKind(str, Enum):
    ACQUIRED = "acquired"
    ALREADY_SUCCEEDED = "already_succeeded"
    IN_FLIGHT = "in_flight"


@dataclass(frozen=True)
class LedgerRecord:
    execution_id: str
    status: LedgerStatus
    result: ExecutionResult | None = None
    grant_id: str | None = None
    request_id: str | None = None
    lease_expires_at: datetime | None = None


@dataclass(frozen=True)
class ClaimOutcome:
    kind: ClaimOutcomeKind
    record: LedgerRecord | None = None


def _aware_utc(value: datetime | None = None) -> datetime:
    """Normalize to UTC-aware datetime.

    Naive values (common when SQLite returns timestamps) are treated as UTC.
    """
    instant = value or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        return instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc)


def _lease_expired(lease_expires_at: datetime | None, now: datetime) -> bool:
    if lease_expires_at is None:
        return True
    return _aware_utc(now) >= _aware_utc(lease_expires_at)


class ExecutionReplayLedger(Protocol):
    """Port for durable or in-process replay prevention."""

    def try_claim(
        self,
        execution_id: str,
        *,
        grant_id: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> ClaimOutcome:
        """Atomically claim execution_id for adapter dispatch."""

    def complete_succeeded(self, execution_id: str, result: ExecutionResult) -> None:
        """Mark claim terminal-success and store the result for REPLAYED."""

    def complete_failed(self, execution_id: str, result: ExecutionResult) -> None:
        """Mark claim failed (retryable) and store the last failure result."""

    def abandon(self, execution_id: str) -> None:
        """Drop a pending claim without locking (e.g. pre-adapter reject)."""

    def get(self, execution_id: str) -> LedgerRecord | None:
        """Return the current record if any."""


@dataclass
class InMemoryReplayLedger:
    """Process-local ledger implementing the P4-01 state machine with leases."""

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
                # Expired pending — reclaim (RA-3)

            if current is None or current.status in {
                LedgerStatus.FAILED,
                LedgerStatus.PENDING,
            }:
                record = LedgerRecord(
                    execution_id=execution_id,
                    status=LedgerStatus.PENDING,
                    result=None,
                    grant_id=grant_id,
                    request_id=request_id,
                    lease_expires_at=lease_until,
                )
                self._records[execution_id] = record
                return ClaimOutcome(kind=ClaimOutcomeKind.ACQUIRED, record=record)

            raise RuntimeError(f"unknown ledger status {current.status!r}")

    def complete_succeeded(self, execution_id: str, result: ExecutionResult) -> None:
        with self._lock:
            current = self._records.get(execution_id)
            if current is None or current.status is not LedgerStatus.PENDING:
                raise RuntimeError(
                    f"complete_succeeded requires pending claim for {execution_id!r}"
                )
            if result.status is not ExecutionStatus.SUCCEEDED:
                raise ValueError("complete_succeeded requires SUCCEEDED result")
            self._records[execution_id] = replace(
                current,
                status=LedgerStatus.SUCCEEDED,
                result=result,
                lease_expires_at=None,
            )

    def complete_failed(self, execution_id: str, result: ExecutionResult) -> None:
        with self._lock:
            current = self._records.get(execution_id)
            if current is None or current.status is not LedgerStatus.PENDING:
                raise RuntimeError(
                    f"complete_failed requires pending claim for {execution_id!r}"
                )
            if result.status is not ExecutionStatus.FAILED:
                raise ValueError("complete_failed requires FAILED result")
            self._records[execution_id] = replace(
                current,
                status=LedgerStatus.FAILED,
                result=result,
                lease_expires_at=None,
            )

    def abandon(self, execution_id: str) -> None:
        with self._lock:
            current = self._records.get(execution_id)
            if current is not None and current.status is LedgerStatus.PENDING:
                del self._records[execution_id]

    def get(self, execution_id: str) -> LedgerRecord | None:
        with self._lock:
            return self._records.get(execution_id)
