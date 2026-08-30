"""Tamper-evident hash-chained audit harness for Phase 6 execution.

The harness appends :class:`ExecutionAuditEvent` records into a single
append-only chain.  Every entry carries the digest of its predecessor, so the
chain root (``head_hash``) commits the full history: altering, dropping, or
reordering any event invalidates the root and is caught by :meth:`verify`.

The harness is a *persistence-agnostic* verifier: callers may supply any
:class:`AuditSink` (log, database, file) for the appended events, while the
chain integrity itself is fully deterministic and testable in-memory.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from phase6.execution.audit import (
    AuditSink,
    ExecutionAuditEvent,
    NullAuditSink,
)


def _chain_digest(
    previous_hash: str,
    index: int,
    event: ExecutionAuditEvent,
) -> str:
    """Content-addressable digest for one chain entry.

    The JSON payload is canonical (sort_keys, compact separators) so the
    digest is stable across processes and platforms.
    """
    payload = json.dumps(
        {
            "previous_hash": previous_hash,
            "index": index,
            "event": event.as_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class HashChainEntry:
    """One immutable link in the audit chain."""

    index: int
    previous_hash: str
    hash: str
    event: ExecutionAuditEvent

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError("chain index must be non-negative")
        if len(self.previous_hash) != 64 or len(self.hash) != 64:
            raise ValueError("chain hashes must be sha256 hex digests")


GENESIS_HASH = "0" * 64


class AuditHarness:
    """Append-only, tamper-evident audit ledger.

    ``append`` commits the event to the in-memory chain and forwards it to the
    configured sink.  ``verify`` re-hashes every entry and returns the chain
    root hash, raising :class:`ChainIntegrityError` on any mismatch.
    """

    def __init__(
        self,
        sink: AuditSink | None = None,
        *,
        chain_id: str = "default",
    ) -> None:
        self._sink = sink or NullAuditSink()
        self._chain_id = chain_id
        self._entries: list[HashChainEntry] = []
        self._head_hash = GENESIS_HASH

    @property
    def chain_id(self) -> str:
        return self._chain_id

    @property
    def head_hash(self) -> str:
        """Root digest committing the entire chain ("" + every appended hash)."""
        return self._head_hash

    @property
    def length(self) -> int:
        return len(self._entries)

    def append(
        self,
        event: ExecutionAuditEvent,
        *,
        sink: AuditSink | None = None,
    ) -> HashChainEntry:
        """Append one event atomically: chain entry + sink emission.

        The entry is committed to the chain before the sink is notified, so a
        failing sink never corrupts chain integrity.
        """
        index = len(self._entries)
        digest = _chain_digest(self._head_hash, index, event)
        entry = HashChainEntry(
            index=index,
            previous_hash=self._head_hash,
            hash=digest,
            event=event,
        )
        self._entries.append(entry)
        self._head_hash = digest
        (sink or self._sink).emit(event)
        return entry

    def entries(self) -> tuple[HashChainEntry, ...]:
        return tuple(self._entries)

    def verify(self) -> str:
        """Re-hash the entire chain; returns the root hash when intact.

        Raises :class:`ChainIntegrityError` when the chain has been altered
        (mismatched hash, missing link, or reordered entry).
        """
        working_head = GENESIS_HASH
        for index, entry in enumerate(self._entries):
            expected = _chain_digest(working_head, index, entry.event)
            if entry.hash != expected:
                raise ChainIntegrityError(
                    f"entry {index} hash mismatch: stored={entry.hash} computed={expected}"
                )
            if entry.previous_hash != working_head:
                raise ChainIntegrityError(
                    f"entry {index} previous_hash mismatch: stored={entry.previous_hash} expected={working_head}"
                )
            working_head = entry.hash
        if working_head != self._head_hash:
            raise ChainIntegrityError(
                f"head hash mismatch: ledger={self._head_hash} recomputed={working_head}"
            )
        return working_head

    def verify_from(
        self,
        entries: Sequence[HashChainEntry] | Iterable[HashChainEntry],
        *,
        expected_head: str | None = None,
    ) -> str:
        """Verify an external sequence of entries against the same chain rules.

        Useful for replaying a persisted ledger.  ``expected_head`` may be the
        hash committed at ship/release time; a mismatch raises
        :class:`ChainIntegrityError`.
        """
        working_head = GENESIS_HASH
        for index, entry in enumerate(entries):
            expected = _chain_digest(working_head, index, entry.event)
            if entry.hash != expected or entry.previous_hash != working_head:
                raise ChainIntegrityError(f"entry {index} breaks the hash chain")
            working_head = entry.hash
        if expected_head is not None and working_head != expected_head:
            raise ChainIntegrityError(
                f"head mismatch: expected={expected_head} recomputed={working_head}"
            )
        return working_head


class ChainIntegrityError(RuntimeError):
    """Raised when the audit chain no longer verifies."""


__all__ = [
    "GENESIS_HASH",
    "AuditHarness",
    "ChainIntegrityError",
    "HashChainEntry",
]
