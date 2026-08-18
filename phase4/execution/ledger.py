"""P4-01 — Durable Authority & Replay Ledger.

P4-00D secures the *authenticity* of the AI-3 -> AI-4 grant (HMAC signature,
exact binding, lifetime). P4-01 secures *single execution over time and across
processes* for a genuine, bound grant:

    For a given ``execution_id`` an adapter may run at most ONE successful
    side-effecting invocation cluster-wide.

The deduplication key is ``execution_id`` (the SHA-256 of the request fields
and the policy binding), NOT ``grant_id``. A fresh re-issued genuine grant for
the same policy binding therefore replays; a new ``policy_version`` produces a
new ``execution_id`` and is an intentional new execution.

This module defines:

- :class:`LedgerRecord` — the immutable durable record.
- :class:`ExecutionLedger` — the persistence port a durable backend implements.
- :class:`InProcessLedger` — the reference thread-safe implementation that can
  be shared across ``ExecutionEngine`` instances to model multi-worker /
  cross-node behaviour and survives an engine "restart".
- :class:`ReplayPolicy` / :class:`PendingClaimOutcome` — the policy-driven
  behaviour for a concurrent claim on an in-flight execution.

The default engine behaviour (no ledger) is preserved for backwards
compatibility: the legacy in-memory ``_results`` store remains, and a ledger
is only consulted when one is supplied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import Condition, RLock
from typing import Dict, Optional, Protocol

from .models import ExecutionStatus


class PendingClaimOutcome(str, Enum):
    """What happens when a second caller finds an in-flight (pending) claim."""

    REJECT = "reject"  # fail-closed: REJECTED, no wait (default)
    WAIT = "wait"  # block until the in-flight execution commits, then replay


@dataclass(frozen=True)
class ReplayPolicy:
    """Policy for replay/pending behaviour of the ledger.

    The default is fail-closed (``REJECT``). Adapters known to be slow or
    naturally idempotent may opt into ``WAIT`` via configuration.
    """

    pending_claim: PendingClaimOutcome = PendingClaimOutcome.REJECT


@dataclass
class LedgerRecord:
    """Immutable-ish durable record for one ``execution_id``.

    ``status`` transitions pending -> succeeded | failed. ``rejected`` is
    never persisted: a rejected request performs no side effect and carries
    no adapter invocation, so it is not ledgered.
    """

    execution_id: str
    status: ExecutionStatus
    request_id: str
    grant_id: str
    authority_policy_id: str
    authority_policy_version: str
    started_at: str
    completed_at: Optional[str] = None
    adapter_id: Optional[str] = None
    outcome_fingerprint: Optional[str] = None
    error: Optional[str] = None


class ClaimResult(Enum):
    """Outcome of an atomic claim attempt on the ledger."""

    ACQUIRED = "acquired"  # caller owns the execution and must run the adapter
    REPLAYED = "replayed"  # a terminal record already exists
    PENDING = "pending"  # an in-flight record exists; apply the pending policy


class ExecutionLedger(Protocol):
    """Persistence port for a durable replay ledger.

    Implementations MUST be safe to share across processes/threads that belong
    to the same signing domain. The contract is:

    1. ``claim`` is atomic. Inserting ``pending`` for an ``execution_id`` that
       already has a record returns ``REPLAYED`` (terminal) or ``PENDING``
       (in-flight); it never creates a second pending record.
    2. ``complete`` transitions the owning pending record to a terminal
       status. Only the owner may complete; a concurrent completer is ignored.
    3. ``get`` returns the terminal record if present.
    4. Records are append/transition-only: a terminal record is never mutated.
    """

    def claim(
        self,
        execution_id: str,
        *,
        request_id: str,
        grant_id: str,
        authority_policy_id: str,
        authority_policy_version: str,
        started_at: str,
    ) -> tuple[ClaimResult, Optional[LedgerRecord]]:
        """Atomically insert a pending claim or return the existing record."""
        ...

    def complete(
        self,
        execution_id: str,
        *,
        status: ExecutionStatus,
        adapter_id: str,
        outcome_fingerprint: Optional[str],
        completed_at: str,
        error: Optional[str],
    ) -> None:
        """Transition the owning pending record to a terminal status."""
        ...

    def get(self, execution_id: str) -> Optional[LedgerRecord]:
        """Return the terminal record for ``execution_id`` if present."""
        ...

    def wait_for_terminal(self, execution_id: str, *, timeout: float = 5.0) -> Optional[LedgerRecord]:
        """Block until the record for ``execution_id`` is terminal or timeout."""
        ...


class InProcessLedger:
    """Reference thread-safe in-process durable ledger.

    It is "durable" relative to the engine: it outlives any single
    ``ExecutionEngine`` instance and can be shared between engines to model
    multi-worker / cross-node replay. A real backend (DB/queue) implements the
    same :class:`ExecutionLedger` protocol with disk-backed persistence.
    """

    def __init__(self) -> None:
        self._records: Dict[str, LedgerRecord] = {}
        self._lock = RLock()
        self._cond = Condition(self._lock)

    def claim(
        self,
        execution_id: str,
        *,
        request_id: str,
        grant_id: str,
        authority_policy_id: str,
        authority_policy_version: str,
        started_at: str,
    ) -> tuple[ClaimResult, Optional[LedgerRecord]]:
        with self._lock:
            existing = self._records.get(execution_id)
            if existing is not None:
                # Check pending FIRST: the sentinel reuses a status value, so
                # pending-ness is carried by the _PENDING_MARKER adapter_id.
                if self._is_pending(existing):
                    return ClaimResult.PENDING, existing
                if existing.status is ExecutionStatus.SUCCEEDED or existing.status is ExecutionStatus.FAILED:
                    return ClaimResult.REPLAYED, existing
                if existing.status is ExecutionStatus.REJECTED:
                    return ClaimResult.REPLAYED, existing
                # pending -> in flight
                return ClaimResult.PENDING, existing
            record = LedgerRecord(
                execution_id=execution_id,
                status=ExecutionStatus.SUCCEEDED,  # placeholder; set below
                request_id=request_id,
                grant_id=grant_id,
                authority_policy_id=authority_policy_id,
                authority_policy_version=authority_policy_version,
                started_at=started_at,
            )
            # Mark pending via a sentinel status carried by a separate flag.
            self._records[execution_id] = self._pending(record)
            return ClaimResult.ACQUIRED, None

    def complete(
        self,
        execution_id: str,
        *,
        status: ExecutionStatus,
        adapter_id: str,
        outcome_fingerprint: Optional[str],
        completed_at: str,
        error: Optional[str],
    ) -> None:
        with self._cond:
            existing = self._records.get(execution_id)
            if existing is None:
                return
            # Only the owner (a pending record) may complete.
            if not self._is_pending(existing):
                return
            self._records[execution_id] = LedgerRecord(
                execution_id=existing.execution_id,
                status=status,
                request_id=existing.request_id,
                grant_id=existing.grant_id,
                authority_policy_id=existing.authority_policy_id,
                authority_policy_version=existing.authority_policy_version,
                started_at=existing.started_at,
                completed_at=completed_at,
                adapter_id=adapter_id,
                outcome_fingerprint=outcome_fingerprint,
                error=error,
            )
            self._cond.notify_all()

    def get(self, execution_id: str) -> Optional[LedgerRecord]:
        with self._lock:
            record = self._records.get(execution_id)
            if record is None or self._is_pending(record):
                return None
            return record

    def wait_for_terminal(self, execution_id: str, *, timeout: float = 5.0) -> Optional[LedgerRecord]:
        with self._cond:
            record = self._records.get(execution_id)
            if record is not None and not self._is_pending(record):
                return record
            self._cond.wait(timeout=timeout)
            record = self._records.get(execution_id)
            if record is None or self._is_pending(record):
                return None
            return record

    # -- pending sentinel helpers ------------------------------------------------

    _PENDING_MARKER = "__p4_01_pending__"

    @staticmethod
    def _pending(record: LedgerRecord) -> LedgerRecord:
        return LedgerRecord(
            execution_id=record.execution_id,
            status=ExecutionStatus.REJECTED,  # unused; pending-ness via adapter_id
            request_id=record.request_id,
            grant_id=record.grant_id,
            authority_policy_id=record.authority_policy_id,
            authority_policy_version=record.authority_policy_version,
            started_at=record.started_at,
            completed_at=None,
            adapter_id=InProcessLedger._PENDING_MARKER,
            outcome_fingerprint=None,
            error=None,
        )

    @staticmethod
    def _is_pending(record: LedgerRecord) -> bool:
        return record.adapter_id == InProcessLedger._PENDING_MARKER
