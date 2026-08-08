"""Immutable, deterministic orchestration contracts for P3-22."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Iterable

from domain.distribution import DispatchRecord
from domain.verification import DeliveredProduct, VerificationResult


class OrchestrationError(ValueError):
    """Raised when orchestration input or a lifecycle transition is invalid."""


class OrchestrationState(str, Enum):
    RECEIVED = "RECEIVED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    EXECUTED = "EXECUTED"
    VERIFIED = "VERIFIED"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


TERMINAL_STATES = frozenset({OrchestrationState.COMPLETED, OrchestrationState.FAILED, OrchestrationState.ESCALATED})
_ALLOWED_TRANSITIONS = {
    OrchestrationState.RECEIVED: frozenset({OrchestrationState.DISPATCHED, OrchestrationState.FAILED}),
    OrchestrationState.DISPATCHED: frozenset({OrchestrationState.DELIVERED, OrchestrationState.FAILED}),
    OrchestrationState.DELIVERED: frozenset({OrchestrationState.EXECUTED, OrchestrationState.FAILED}),
    OrchestrationState.EXECUTED: frozenset({OrchestrationState.VERIFIED, OrchestrationState.FAILED}),
    OrchestrationState.VERIFIED: frozenset({OrchestrationState.COMPLETED, OrchestrationState.RETRYING, OrchestrationState.ESCALATED, OrchestrationState.FAILED}),
    OrchestrationState.RETRYING: frozenset({OrchestrationState.DISPATCHED, OrchestrationState.FAILED}),
    OrchestrationState.COMPLETED: frozenset(),
    OrchestrationState.FAILED: frozenset(),
    OrchestrationState.ESCALATED: frozenset(),
}


@dataclass(frozen=True)
class RetryPolicy:
    policy_id: str = "no-retry"
    max_attempts: int = 1
    retryable_failures: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise OrchestrationError("policy_id must be non-empty")
        if self.max_attempts < 1:
            raise OrchestrationError("max_attempts must be at least 1")
        if len(self.retryable_failures) != len(set(self.retryable_failures)):
            raise OrchestrationError("retryable_failures must be unique")

    def can_retry(self, failure: str, attempt: int) -> bool:
        return attempt < self.max_attempts and failure in self.retryable_failures


@dataclass(frozen=True)
class OrchestrationRequest:
    task_id: str
    task_fingerprint: str
    package_id: str
    package_fingerprint: str
    available_inputs: tuple[str, ...]
    selected_role: str
    policy: RetryPolicy = RetryPolicy()

    def __post_init__(self) -> None:
        for name, value in (
            ("task_id", self.task_id), ("task_fingerprint", self.task_fingerprint),
            ("package_id", self.package_id), ("package_fingerprint", self.package_fingerprint),
            ("selected_role", self.selected_role),
        ):
            if not isinstance(value, str) or not value.strip():
                raise OrchestrationError(f"{name} must be non-empty")
        if not self.available_inputs:
            raise OrchestrationError("available_inputs must not be empty")
        if len(self.available_inputs) != len(set(self.available_inputs)):
            raise OrchestrationError("available_inputs must be unique")

    @property
    def orchestration_id(self) -> str:
        payload = {
            "task_id": self.task_id,
            "task_fingerprint": self.task_fingerprint,
            "package_id": self.package_id,
            "package_fingerprint": self.package_fingerprint,
            "available_inputs": list(self.available_inputs),
            "selected_role": self.selected_role,
            "policy_id": self.policy.policy_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return "orchestration-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class OrchestrationSnapshot:
    orchestration_id: str
    state: OrchestrationState
    attempt: int = 1
    dispatch_fingerprint: str | None = None
    artifact_fingerprint: str | None = None
    verification_fingerprint: str | None = None
    failure_reason: str | None = None

    def transition(self, target: OrchestrationState, *, failure_reason: str | None = None) -> "OrchestrationSnapshot":
        allowed = _ALLOWED_TRANSITIONS[self.state]
        if target not in allowed:
            raise OrchestrationError(f"Invalid transition: {self.state.value} -> {target.value}")
        attempt = self.attempt + 1 if target == OrchestrationState.RETRYING else self.attempt
        return OrchestrationSnapshot(self.orchestration_id, target, attempt, self.dispatch_fingerprint,
                                     self.artifact_fingerprint, self.verification_fingerprint, failure_reason)

    def bind_dispatch(self, dispatch: DispatchRecord) -> "OrchestrationSnapshot":
        if dispatch.fingerprint == "":
            raise OrchestrationError("dispatch fingerprint must be non-empty")
        return OrchestrationSnapshot(self.orchestration_id, self.state, self.attempt, dispatch.fingerprint,
                                     self.artifact_fingerprint, self.verification_fingerprint, self.failure_reason)

    def bind_product(self, product: DeliveredProduct) -> "OrchestrationSnapshot":
        return OrchestrationSnapshot(self.orchestration_id, self.state, self.attempt, self.dispatch_fingerprint,
                                     product.artifact_fingerprint, self.verification_fingerprint, self.failure_reason)

    def bind_verification(self, result: VerificationResult) -> "OrchestrationSnapshot":
        return OrchestrationSnapshot(self.orchestration_id, self.state, self.attempt, self.dispatch_fingerprint,
                                     self.artifact_fingerprint, result.fingerprint, self.failure_reason)


@dataclass(frozen=True)
class OrchestrationResult:
    orchestration_id: str
    final_state: OrchestrationState
    attempt: int
    dispatch_fingerprint: str | None = None
    artifact_fingerprint: str | None = None
    verification_fingerprint: str | None = None
    failure_reason: str | None = None
