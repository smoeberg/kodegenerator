"""Immutable Phase 4 Brain and Workforce domain contracts.

These contracts deliberately separate agent identity, assignment state,
worker execution, and epistemic verification. They contain no orchestration,
LLM calls, persistence, or execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AssignmentState(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Assignment:
    """A durable unit of work assigned to an agent identity.

    Worker ownership is transient execution metadata; it does not become part
    of the agent identity and can safely disappear on worker failure.
    """

    assignment_id: str
    task_id: str
    agent_id: str
    state: AssignmentState = AssignmentState.PENDING
    attempt: int = 0
    worker_id: str | None = None
    lease_until: str | None = None

    def __post_init__(self) -> None:
        if not self.assignment_id.strip():
            raise ValueError("assignment_id must be non-empty")
        if not self.task_id.strip():
            raise ValueError("task_id must be non-empty")
        if not self.agent_id.strip():
            raise ValueError("agent_id must be non-empty")
        if self.attempt < 0:
            raise ValueError("attempt must be non-negative")
        if (self.worker_id is None) != (self.lease_until is None):
            raise ValueError("worker_id and lease_until must be provided together")


@dataclass(frozen=True)
class Evidence:
    """Immutable evidence supporting or contradicting a claim.

    ``acceptance_criterion`` optionally links the evidence item to one
    acceptance criterion of the spec (an AC id or short label), which lets
    judges report per-criterion coverage instead of a single all-or-nothing
    verdict.
    """

    evidence_id: str
    source: str
    content_digest: str
    supports: bool = True
    acceptance_criterion: str = ""

    def __post_init__(self) -> None:
        if not self.evidence_id.strip():
            raise ValueError("evidence_id must be non-empty")
        if not self.source.strip():
            raise ValueError("evidence source must be non-empty")
        if not self.content_digest.strip():
            raise ValueError("evidence content_digest must be non-empty")


class KnowledgeState(str, Enum):
    PROPOSED = "proposed"
    DISPUTED = "disputed"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class KnowledgeRecord:
    """Append-only epistemic record.

    A record is immutable. The version identifies the materialized knowledge
    state observed when this record was produced; concurrent writers must not
    silently overwrite a newer version.
    """

    record_id: str
    subject: str
    claim: str
    evidence: tuple[Evidence, ...] = ()
    state: KnowledgeState = KnowledgeState.PROPOSED
    version: int = 0
    author_agent_id: str = ""

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise ValueError("record_id must be non-empty")
        if not self.subject.strip():
            raise ValueError("subject must be non-empty")
        if not self.claim.strip():
            raise ValueError("claim must be non-empty")
        if self.version < 0:
            raise ValueError("version must be non-negative")
        if not self.author_agent_id.strip():
            raise ValueError("author_agent_id must be non-empty")


@dataclass(frozen=True)
class MaterializedKnowledgeState:
    """Materialized aggregate knowledge state for a subject."""

    subject: str
    claim: str
    evidence: tuple[Evidence, ...] = ()
    state: KnowledgeState = KnowledgeState.PROPOSED
    version: int = 0

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("subject must be non-empty")
        if not self.claim.strip():
            raise ValueError("claim must be non-empty")
        if self.version < 0:
            raise ValueError("version must be non-negative")


class VerificationMode(str, Enum):
    DETERMINISTIC = "deterministic"
    SINGLE_AGENT = "single_agent"
    QUORUM = "quorum"
    HUMAN = "human"


@dataclass(frozen=True)
class VerificationPolicy:
    """Policy describing how a claim must be verified.

    Policy selection is separate from execution authority. Confirmation of a
    claim never creates a VerifiedAuthorityGrant.
    """

    mode: VerificationMode
    quorum_size: int = 1
    risk_level: int = 0
    escalation_timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.quorum_size < 1:
            raise ValueError("quorum_size must be positive")
        if self.risk_level < 0:
            raise ValueError("risk_level must be non-negative")
        if self.mode is VerificationMode.QUORUM and self.quorum_size < 2:
            raise ValueError("quorum verification requires at least two votes")
        if self.mode is not VerificationMode.QUORUM and self.quorum_size != 1:
            raise ValueError("quorum_size is only configurable for quorum mode")
        if self.escalation_timeout_seconds is not None and self.escalation_timeout_seconds < 1:
            raise ValueError("escalation timeout must be positive")
