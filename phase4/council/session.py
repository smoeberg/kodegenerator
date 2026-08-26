"""Deliberation session and dispute protocol state machine for the Dialectical Council."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

from phase4.epistemics.models import Hypothesis


class SessionState(str, Enum):
    OPEN = "open"
    IN_DISPUTE = "in_dispute"
    DECISION_READY = "decision_ready"
    DEADLOCKED = "deadlocked"
    RESOLVED = "resolved"


class Dispute(BaseModel):
    dispute_id: str
    hypothesis_id: str
    challenger_role: str
    argument: str
    critical: bool = True
    resolved: bool = False
    resolution_note: Optional[str] = None


class DeliberationSession(BaseModel):
    session_id: str
    task_id: str
    state: SessionState = SessionState.OPEN
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    disputes: List[Dispute] = Field(default_factory=list)
    round_count: int = 0
    max_rounds: int = 4

    def add_hypothesis(self, hypothesis: Hypothesis) -> None:
        self.hypotheses.append(hypothesis)

    def raise_dispute(self, dispute: Dispute) -> None:
        self.disputes.append(dispute)
        self.state = SessionState.IN_DISPUTE

    def resolve_dispute(self, dispute_id: str, resolution_note: str) -> None:
        for d in self.disputes:
            if d.dispute_id == dispute_id:
                d.resolved = True
                d.resolution_note = resolution_note
        
        # Check if any critical disputes remain unresolved
        if not any(not d.resolved and d.critical for d in self.disputes):
            self.state = SessionState.DECISION_READY

    def advance_round(self) -> None:
        self.round_count += 1
        if self.round_count >= self.max_rounds and any(not d.resolved and d.critical for d in self.disputes):
            self.state = SessionState.DEADLOCKED
