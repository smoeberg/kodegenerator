"""Durable Council runtime and execution-event contracts.

These contracts bind every persisted deliberation and execution observation to
an organization, hypothesis revision, workspace revision, and context packet.
They intentionally contain no execution or authority capability.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from phase4.adaptation.models import ExecutionFailure, StrategyFingerprint

if TYPE_CHECKING:
    from .session import DeliberationSession


def _strategy_digest(fingerprint: StrategyFingerprint) -> str:
    payload = {
        "hypothesis_id": fingerprint.hypothesis_id,
        "affected_files": sorted(set(fingerprint.affected_files)),
        "change_pattern": fingerprint.change_pattern.strip().lower(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _failure_identity(failure: ExecutionFailure) -> dict[str, Any]:
    return failure.model_dump(
        mode="json",
        exclude={"failure_id", "timestamp"},
    )


def _execution_event_id(
    *,
    organization_id: str,
    session_id: str,
    hypothesis_id: str,
    hypothesis_revision: str,
    workspace_revision: str,
    context_packet_id: str,
    execution_id: str,
    fingerprint: StrategyFingerprint,
    failure: ExecutionFailure,
) -> str:
    identity = {
        "organization_id": organization_id,
        "session_id": session_id,
        "hypothesis_id": hypothesis_id,
        "hypothesis_revision": hypothesis_revision,
        "workspace_revision": workspace_revision,
        "context_packet_id": context_packet_id,
        "execution_id": execution_id,
        "fingerprint_hash": fingerprint.summary_hash,
        "failure": _failure_identity(failure),
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class CouncilRuntimeEventType(str, Enum):
    SESSION_CREATED = "COUNCIL_SESSION_CREATED"
    FAILURE_OBSERVED = "COUNCIL_FAILURE_OBSERVED"
    PIVOT_REQUIRED = "COUNCIL_PIVOT_REQUIRED"
    ENVIRONMENT_HALT_REQUIRED = "COUNCIL_ENVIRONMENT_HALT_REQUIRED"
    POLICY_ESCALATION_REQUIRED = "COUNCIL_POLICY_ESCALATION_REQUIRED"
    HUMAN_REQUIRED = "COUNCIL_HUMAN_REQUIRED"


class CouncilSessionBinding(BaseModel):
    """Immutable provenance binding for one deliberation session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    organization_id: str = Field(min_length=1)
    context_packet_id: str = Field(min_length=1)
    hypothesis_revision: str = Field(min_length=1)
    workspace_revision: str = Field(min_length=1)


@dataclass(frozen=True)
class PersistedDeliberation:
    """Rehydrated session plus its durable concurrency/provenance metadata."""

    session: DeliberationSession
    binding: CouncilSessionBinding
    state_version: int


class CouncilOutboxEvent(BaseModel):
    """Organization-scoped event awaiting publication after commit."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    organization_id: str
    event_type: CouncilRuntimeEventType
    aggregate_id: str
    payload: dict[str, Any]
    correlation_id: str | None = None
    created_at: datetime


class ExecutionFailedEvent(BaseModel):
    """Canonical AI-4 failure observation consumed by the Anti-Tube boundary."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str = Field(min_length=1)
    organization_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    hypothesis_id: str = Field(min_length=1)
    hypothesis_revision: str = Field(min_length=1)
    workspace_revision: str = Field(min_length=1)
    context_packet_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    fingerprint: StrategyFingerprint
    failure: ExecutionFailure
    correlation_id: str | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_bindings(self) -> ExecutionFailedEvent:
        if self.fingerprint.hypothesis_id != self.hypothesis_id:
            raise ValueError("strategy fingerprint is bound to another hypothesis")
        if self.fingerprint.summary_hash != _strategy_digest(self.fingerprint):
            raise ValueError("strategy fingerprint digest is invalid")
        expected_event_id = _execution_event_id(
            organization_id=self.organization_id,
            session_id=self.session_id,
            hypothesis_id=self.hypothesis_id,
            hypothesis_revision=self.hypothesis_revision,
            workspace_revision=self.workspace_revision,
            context_packet_id=self.context_packet_id,
            execution_id=self.execution_id,
            fingerprint=self.fingerprint,
            failure=self.failure,
        )
        if self.event_id != expected_event_id:
            raise ValueError("execution failure event digest is invalid")
        return self

    @classmethod
    def create(
        cls,
        *,
        organization_id: str,
        session_id: str,
        hypothesis_id: str,
        hypothesis_revision: str,
        workspace_revision: str,
        context_packet_id: str,
        execution_id: str,
        fingerprint: StrategyFingerprint,
        failure: ExecutionFailure,
        correlation_id: str | None = None,
    ) -> ExecutionFailedEvent:
        return cls(
            event_id=_execution_event_id(
                organization_id=organization_id,
                session_id=session_id,
                hypothesis_id=hypothesis_id,
                hypothesis_revision=hypothesis_revision,
                workspace_revision=workspace_revision,
                context_packet_id=context_packet_id,
                execution_id=execution_id,
                fingerprint=fingerprint,
                failure=failure,
            ),
            organization_id=organization_id,
            session_id=session_id,
            hypothesis_id=hypothesis_id,
            hypothesis_revision=hypothesis_revision,
            workspace_revision=workspace_revision,
            context_packet_id=context_packet_id,
            execution_id=execution_id,
            fingerprint=fingerprint,
            failure=failure,
            correlation_id=correlation_id,
        )
