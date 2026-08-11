"""P5-09 resolution execution boundary.

Validates a P5-08 release resolution and deterministically constructs an
immutable execution request. No execution or external side effect occurs.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Any


class ExecutionKind(str, Enum):
    RETRY = "RETRY"
    ESCALATION = "ESCALATION"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class ExecutionPolicy:
    adapter_id: str | None = None
    authorized: bool = False


@dataclass(frozen=True)
class ExecutionRequest:
    request_id: str
    resolution_id: str
    resolution_fingerprint: str
    disposition: Any
    execution_kind: ExecutionKind
    adapter_id: str


class ExecutionBoundary:
    def prepare(self, resolution: Any, policy: ExecutionPolicy) -> ExecutionRequest | None:
        self._validate_resolution(resolution)
        disposition = resolution.disposition
        value = getattr(disposition, "value", disposition)

        if value == "NO_ACTION":
            return None
        if value == "RELEASE_BLOCKED":
            raise PermissionError("RELEASE_BLOCKED cannot produce release execution")
        if value == "RETRY_REQUESTED":
            kind = ExecutionKind.RETRY
        elif value == "ESCALATION_REQUIRED":
            kind = ExecutionKind.ESCALATION
        else:
            raise ValueError(f"unsupported release disposition: {value!r}")

        if not policy.adapter_id or not policy.authorized:
            raise PermissionError("an explicitly authorized execution adapter is required")

        fingerprint = resolution.fingerprint
        request_id = self._request_id(
            resolution.resolution_id, fingerprint, value, kind.value, policy.adapter_id
        )
        return ExecutionRequest(
            request_id=request_id,
            resolution_id=resolution.resolution_id,
            resolution_fingerprint=fingerprint,
            disposition=disposition,
            execution_kind=kind,
            adapter_id=policy.adapter_id,
        )

    @staticmethod
    def _validate_resolution(resolution: Any) -> None:
        required = (
            "resolution_id", "disposition", "fingerprint", "reconciliation_id",
            "reconciliation_fingerprint", "dispatch_id", "outcome_id",
            "finalization_fingerprint", "verifier_id", "release_id",
            "policy_fingerprint",
        )
        for field in required:
            if not getattr(resolution, field, None):
                raise ValueError(f"missing resolution provenance: {field}")

    @staticmethod
    def _request_id(resolution_id: str, fingerprint: str, disposition: str,
                    execution_kind: str, adapter_id: str) -> str:
        payload = json.dumps({
            "adapter_id": adapter_id,
            "disposition": disposition,
            "execution_kind": execution_kind,
            "resolution_fingerprint": fingerprint,
            "resolution_id": resolution_id,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
