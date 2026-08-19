"""P4-01 replay ledger: EMPTY -> PENDING -> SUCCEEDED/FAILED/ABANDONED."""
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
    ABANDONED = "abandoned"

class ClaimOutcomeKind(str, Enum):
    ACQUIRED = "acquired"
    ALREADY_SUCCEEDED = "already_succeeded"
    IN_FLIGHT = "in_flight"

class StaleClaimTokenError(RuntimeError):
    """A completion/abandon operation does not own the current claim."""

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
        raise ValueError("ledger timestamps must be timezone-aware")
    return instant.astimezone(timezone.utc)

def _lease_expired(value: datetime | None, now: datetime) -> bool:
    return value is None or _aware_utc(now) >= _aware_utc(value)

def _new_token() -> str:
    return secrets.token_urlsafe(16)

class ExecutionReplayLedger(Protocol):
    def try_claim(self, execution_id: str, *, grant_id: str | None = None, request_id: str | None = None, now: datetime | None = None) -> ClaimOutcome: ...
    def complete_succeeded(self, execution_id: str, result: ExecutionResult, *, fencing_token: str) -> None: ...
    def complete_failed(self, execution_id: str, result: ExecutionResult, *, fencing_token: str) -> None: ...
    def abandon(self, execution_id: str, *, fencing_token: str) -> None: ...
    def get(self, execution_id: str) -> LedgerRecord | None: ...

@dataclass
class InMemoryReplayLedger:
    claim_lease_seconds: int = DEFAULT_CLAIM_LEASE_SECONDS
    _records: dict[str, LedgerRecord] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def __post_init__(self) -> None:
        if type(self.claim_lease_seconds) is not int or self.claim_lease_seconds < 1:
            raise ValueError("claim_lease_seconds must be a positive int")

    def try_claim(self, execution_id: str, *, grant_id: str | None = None, request_id: str | None = None, now: datetime | None = None) -> ClaimOutcome:
        if not execution_id.strip(): raise ValueError("execution_id must be non-empty")
        instant = _aware_utc(now); lease = instant + timedelta(seconds=self.claim_lease_seconds)
        with self._lock:
            current = self._records.get(execution_id)
            if current and current.status is LedgerStatus.SUCCEEDED: return ClaimOutcome(ClaimOutcomeKind.ALREADY_SUCCEEDED, current)
            if current and current.status is LedgerStatus.PENDING and not _lease_expired(current.lease_expires_at, instant): return ClaimOutcome(ClaimOutcomeKind.IN_FLIGHT, current)
            record = LedgerRecord(execution_id, LedgerStatus.PENDING, None, grant_id, request_id, lease, _new_token())
            self._records[execution_id] = record
            return ClaimOutcome(ClaimOutcomeKind.ACQUIRED, record)

    def _pending(self, execution_id: str, token: str) -> LedgerRecord:
        current = self._records.get(execution_id)
        if current is None or current.status is not LedgerStatus.PENDING: raise RuntimeError(f"claim is not pending for {execution_id!r}")
        if not token or current.fencing_token != token: raise StaleClaimTokenError(f"fencing token mismatch for {execution_id!r}")
        return current

    def complete_succeeded(self, execution_id: str, result: ExecutionResult, *, fencing_token: str) -> None:
        if result.status is not ExecutionStatus.SUCCEEDED: raise ValueError("complete_succeeded requires SUCCEEDED result")
        with self._lock:
            current=self._pending(execution_id,fencing_token); self._records[execution_id]=replace(current,status=LedgerStatus.SUCCEEDED,result=result,lease_expires_at=None,fencing_token=None)

    def complete_failed(self, execution_id: str, result: ExecutionResult, *, fencing_token: str) -> None:
        if result.status is not ExecutionStatus.FAILED: raise ValueError("complete_failed requires FAILED result")
        with self._lock:
            current=self._pending(execution_id,fencing_token); self._records[execution_id]=replace(current,status=LedgerStatus.FAILED,result=result,lease_expires_at=None,fencing_token=None)

    def abandon(self, execution_id: str, *, fencing_token: str) -> None:
        with self._lock:
            current=self._records.get(execution_id)
            if current is None or current.status is not LedgerStatus.PENDING: return
            if not fencing_token or current.fencing_token != fencing_token: raise StaleClaimTokenError(f"fencing token mismatch for {execution_id!r}")
            self._records[execution_id]=replace(current,status=LedgerStatus.ABANDONED,lease_expires_at=None,fencing_token=None)

    def get(self, execution_id: str) -> LedgerRecord | None:
        with self._lock: return self._records.get(execution_id)
