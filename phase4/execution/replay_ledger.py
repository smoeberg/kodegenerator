"""P4-01 execution replay ledger — state machine for single-flight claims.

Invariant: for a given execution_id the adapter may perform at most one
*successful* side-effecting invocation (cluster-wide once a durable backend
is plugged in). Failed and abandoned attempts do not permanently lock the id;
abandoned rows are retained for audit (append-only).

State machine::

    (empty|failed|abandoned) ──claim──► pending ──complete(succeeded)──► succeeded
                                           │
                                           ├──complete(failed)──► failed
                                           ├──abandon───────────► abandoned
                                           └──concurrent claim──► IN_FLIGHT

    succeeded ──claim──► ALREADY_SUCCEEDED
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
from threading import RLock
from typing import Protocol

from .models import ExecutionResult, ExecutionStatus


class LedgerStatus(str, Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    ABANDONED = "abandoned"


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


@dataclass(frozen=True)
class ClaimOutcome:
    kind: ClaimOutcomeKind
    record: LedgerRecord | None = None


_RECLAIMABLE = frozenset({LedgerStatus.FAILED, LedgerStatus.ABANDONED})


class ExecutionReplayLedger(Protocol):
    """Port for durable or in-process replay prevention."""

    def try_claim(
        self,
        execution_id: str,
        *,
        grant_id: str | None = None,
        request_id: str | None = None,
    ) -> ClaimOutcome:
        """Atomically claim execution_id for adapter dispatch."""

    def complete_succeeded(self, execution_id: str, result: ExecutionResult) -> None:
        """Mark claim terminal-success and store the result for REPLAYED."""

    def complete_failed(self, execution_id: str, result: ExecutionResult) -> None:
        """Mark claim failed (retryable) and store the last failure result."""

    def abandon(self, execution_id: str) -> None:
        """Mark pending claim abandoned without deleting the row (audit retained)."""

    def get(self, execution_id: str) -> LedgerRecord | None:
        """Return the current record if any."""


@dataclass
class InMemoryReplayLedger:
    """Process-local ledger implementing the P4-01 state machine."""

    _records: dict[str, LedgerRecord] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock)

    def try_claim(
        self,
        execution_id: str,
        *,
        grant_id: str | None = None,
        request_id: str | None = None,
    ) -> ClaimOutcome:
        if not execution_id or not execution_id.strip():
            raise ValueError("execution_id must be non-empty")
        with self._lock:
            current = self._records.get(execution_id)
            if current is None or current.status in _RECLAIMABLE:
                record = LedgerRecord(
                    execution_id=execution_id,
                    status=LedgerStatus.PENDING,
                    result=None,
                    grant_id=grant_id,
                    request_id=request_id,
                )
                self._records[execution_id] = record
                return ClaimOutcome(kind=ClaimOutcomeKind.ACQUIRED, record=record)
            if current.status is LedgerStatus.SUCCEEDED:
                return ClaimOutcome(
                    kind=ClaimOutcomeKind.ALREADY_SUCCEEDED,
                    record=current,
                )
            return ClaimOutcome(kind=ClaimOutcomeKind.IN_FLIGHT, record=current)

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
            )

    def abandon(self, execution_id: str) -> None:
        with self._lock:
            current = self._records.get(execution_id)
            if current is not None and current.status is LedgerStatus.PENDING:
                self._records[execution_id] = replace(
                    current,
                    status=LedgerStatus.ABANDONED,
                    result=None,
                )

    def get(self, execution_id: str) -> LedgerRecord | None:
        with self._lock:
            return self._records.get(execution_id)
