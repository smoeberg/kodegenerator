"""Phase 4 AI-5 immutable outcome and state-transition models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple
import hashlib
import json

from phase4.execution.models import ExecutionResult, ExecutionStatus


class OutcomeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    REPLAYED = "replayed"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StateTransition:
    subject_id: str
    from_state: str
    to_state: str


@dataclass(frozen=True)
class OutcomeRecord:
    outcome_id: str
    execution_id: str
    request_id: str
    status: OutcomeStatus
    transitions: Tuple[StateTransition, ...]
    provenance_id: str
    produced_at: str
    error: Optional[str] = None

    @property
    def terminal(self) -> bool:
        return self.status is not OutcomeStatus.UNKNOWN


def outcome_status_for(result: ExecutionResult, *, unknown: bool = False) -> OutcomeStatus:
    if unknown:
        return OutcomeStatus.UNKNOWN
    return {
        ExecutionStatus.SUCCEEDED: OutcomeStatus.SUCCEEDED,
        ExecutionStatus.FAILED: OutcomeStatus.FAILED,
        ExecutionStatus.REJECTED: OutcomeStatus.REJECTED,
        ExecutionStatus.REPLAYED: OutcomeStatus.REPLAYED,
    }[result.status]


def outcome_id_for(result: ExecutionResult, status: OutcomeStatus, transitions: Tuple[StateTransition, ...] = ()) -> str:
    payload = {
        "execution_id": result.execution_id,
        "status": status.value,
        "adapter_id": result.adapter_id,
        "output": list(result.output),
        "error": result.error,
        "transitions": [
            {
                "subject_id": t.subject_id,
                "from_state": t.from_state,
                "to_state": t.to_state,
            }
            for t in transitions
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def provenance_id_for(result: ExecutionResult) -> str:
    payload = {
        "execution_id": result.execution_id,
        "request_id": result.request_id,
        "authority_policy_id": result.authority_policy_id,
        "authority_policy_version": result.authority_policy_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
