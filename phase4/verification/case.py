"""Lifecycle contract for a single epistemic verification case."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from .engine import VerificationResult
from .selection import VerifierSelection


class VerificationCaseStatus(str, Enum):
    OPEN = "open"
    COMPLETE = "complete"
    ESCALATED = "escalated"
    EXPIRED = "expired"


@dataclass
class VerificationCase:
    claim_id: str
    policy_id: str
    selection: VerifierSelection
    status: VerificationCaseStatus = VerificationCaseStatus.OPEN
    observations: dict[str, bool] = field(default_factory=dict)
    result: VerificationResult | None = None
    deadline_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.deadline_at is not None and self.deadline_at.tzinfo is None:
            raise ValueError("verification case deadline must be timezone-aware")

    def _ensure_open(self) -> None:
        if self.status is not VerificationCaseStatus.OPEN:
            raise ValueError("verification case is not open")
        if self.deadline_at is not None and datetime.now(timezone.utc) >= self.deadline_at:
            self.status = VerificationCaseStatus.EXPIRED
            raise ValueError("verification case deadline has expired")

    def record(self, agent_id: str, outcome: bool) -> None:
        self._ensure_open()
        if agent_id not in self.selection.selected_ids:
            raise ValueError("agent is not assigned to this verification case")
        if agent_id in self.observations:
            raise ValueError("agent has already submitted an observation")
        self.observations[agent_id] = outcome

    def complete(self, result: VerificationResult) -> None:
        self._ensure_open()
        self.result = result
        self.status = (
            VerificationCaseStatus.COMPLETE
            if result in (VerificationResult.CONFIRMED, VerificationResult.DISPUTED)
            else VerificationCaseStatus.ESCALATED
        )

    def expire(self) -> None:
        if self.status is not VerificationCaseStatus.OPEN:
            raise ValueError("verification case is not open")
        self.status = VerificationCaseStatus.EXPIRED
