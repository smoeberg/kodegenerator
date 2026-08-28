"""Replay-store contracts for exactly-once governed LLM provider calls."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol


class GovernedLLMError(RuntimeError):
    """Base error for the governed model boundary."""


class LLMCallInProgressError(GovernedLLMError):
    """Another worker owns the provider-call lease."""


class LLMReplayConflictError(GovernedLLMError):
    """An idempotency key is bound to different immutable input."""


@dataclass(frozen=True)
class LLMReplayClaim:
    """Fenced ownership or a previously completed result."""

    fencing_token: str | None
    value: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    @property
    def replayed(self) -> bool:
        return self.fencing_token is None


class LLMReplayStore(Protocol):
    """Atomic claim/complete contract shared by local and SQL stores."""

    def claim(
        self, organization_id: str, idempotency_key: str, prompt_fingerprint: str
    ) -> LLMReplayClaim: ...
    def complete(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        value: dict[str, Any],
        provenance: dict[str, Any],
    ) -> None: ...
    def fail(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        failure_class: str,
    ) -> None: ...


class InMemoryLLMReplayStore:
    """Thread-safe development store with the same fenced API as SQL."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def claim(
        self, organization_id: str, idempotency_key: str, prompt_fingerprint: str
    ) -> LLMReplayClaim:
        key = (organization_id, idempotency_key)
        with self._lock:
            row = self._rows.get(key)
            if row is not None:
                if row["prompt_fingerprint"] != prompt_fingerprint:
                    raise LLMReplayConflictError(
                        "idempotency key is bound to different input"
                    )
                if row["status"] == "completed":
                    return LLMReplayClaim(None, row["value"], row["provenance"])
                raise LLMCallInProgressError("LLM call is already in progress")
            token = secrets.token_hex(16)
            self._rows[key] = {
                "prompt_fingerprint": prompt_fingerprint,
                "status": "in_progress",
                "fencing_token": token,
            }
            return LLMReplayClaim(token)

    def complete(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        value: dict[str, Any],
        provenance: dict[str, Any],
    ) -> None:
        with self._lock:
            row = self._owned(
                organization_id, idempotency_key, prompt_fingerprint, fencing_token
            )
            row.update(status="completed", value=value, provenance=provenance)

    def fail(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        failure_class: str,
    ) -> None:
        with self._lock:
            self._owned(
                organization_id, idempotency_key, prompt_fingerprint, fencing_token
            )
            self._rows.pop((organization_id, idempotency_key), None)

    def _owned(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
    ) -> dict[str, Any]:
        row = self._rows.get((organization_id, idempotency_key))
        if (
            row is None
            or row["prompt_fingerprint"] != prompt_fingerprint
            or row["fencing_token"] != fencing_token
            or row["status"] != "in_progress"
        ):
            raise LLMCallInProgressError("stale LLM fencing token")
        return row
