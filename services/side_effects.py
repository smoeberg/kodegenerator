"""Exactly-once coordination boundary for terminal external side effects."""

from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import RLock
from typing import Any, Protocol, TypeVar

T = TypeVar("T", bound=Mapping[str, Any])


class SideEffectInProgressError(RuntimeError):
    """Another worker owns the unexpired side-effect lease."""


class SideEffectConflictError(RuntimeError):
    """An idempotency key was rebound to a different operation."""


@dataclass(frozen=True)
class SideEffectClaim:
    """Fenced ownership or a completed replay result."""

    fencing_token: str | None
    result: dict[str, Any] | None = None

    @property
    def replayed(self) -> bool:
        return self.fencing_token is None


class SideEffectStore(Protocol):
    def claim(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> SideEffectClaim: ...
    def complete(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        result: dict[str, Any],
    ) -> None: ...
    def fail(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        failure_class: str,
    ) -> None: ...


class InMemorySideEffectStore:
    """Thread-safe development implementation of the durable contract."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def claim(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> SideEffectClaim:
        key = (organization_id, action, idempotency_key)
        with self._lock:
            row = self._rows.get(key)
            if row:
                if row["fingerprint"] != request_fingerprint:
                    raise SideEffectConflictError(
                        "side-effect key is bound to different input"
                    )
                if row["status"] == "completed":
                    return SideEffectClaim(None, dict(row["result"]))
                raise SideEffectInProgressError("side effect is already in progress")
            token = secrets.token_hex(16)
            self._rows[key] = {
                "fingerprint": request_fingerprint,
                "status": "in_progress",
                "fencing_token": token,
            }
            return SideEffectClaim(token)

    def complete(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        result: dict[str, Any],
    ) -> None:
        with self._lock:
            row = self._owned(
                organization_id,
                action,
                idempotency_key,
                request_fingerprint,
                fencing_token,
            )
            row.update(status="completed", result=dict(result))

    def fail(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        failure_class: str,
    ) -> None:
        with self._lock:
            self._owned(
                organization_id,
                action,
                idempotency_key,
                request_fingerprint,
                fencing_token,
            )
            self._rows.pop((organization_id, action, idempotency_key))

    def _owned(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
    ) -> dict[str, Any]:
        row = self._rows.get((organization_id, action, idempotency_key))
        if (
            not row
            or row["fingerprint"] != request_fingerprint
            or row["fencing_token"] != fencing_token
            or row["status"] != "in_progress"
        ):
            raise SideEffectInProgressError("stale side-effect fencing token")
        return row


class SideEffectCoordinator:
    """Run an external mutation once and persist its replayable receipt."""

    def __init__(self, store: SideEffectStore | None = None) -> None:
        self._store = store or InMemorySideEffectStore()

    def execute(
        self,
        *,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_data: Mapping[str, Any],
        operation: Callable[[], T],
    ) -> tuple[dict[str, Any], bool]:
        fingerprint = canonical_fingerprint(request_data)
        claim = self._store.claim(organization_id, action, idempotency_key, fingerprint)
        if claim.replayed:
            assert claim.result is not None
            return claim.result, True
        assert claim.fencing_token is not None
        try:
            result = dict(operation())
        except Exception as exc:
            self._store.fail(
                organization_id,
                action,
                idempotency_key,
                fingerprint,
                claim.fencing_token,
                type(exc).__name__,
            )
            raise
        # Receipt persistence is deliberately outside the operation exception
        # handler. If it fails after the external mutation, the active lease is
        # retained instead of being marked retryable and risking a duplicate.
        self._store.complete(
            organization_id,
            action,
            idempotency_key,
            fingerprint,
            claim.fencing_token,
            result,
        )
        return result, False


def canonical_fingerprint(value: Mapping[str, Any]) -> str:
    """Return a stable identity digest for a secret-free operation payload."""
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()
