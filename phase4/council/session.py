"""Deliberation session orchestrating the Council cycle."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from phase4.epistemics.engine import BeliefRevisionEngine
from phase4.epistemics.models import Evidence, Hypothesis, HypothesisStatus
from .dispute import DisputeProtocol, DisputeProtocolError
from .models import Dispute, SessionState, Vote


class DeliberationError(Exception):
    """Raised when an illegal action is performed in a DeliberationSession."""
    pass


class DeliberationSession:
    """Controls a Council deliberation cycle over a hypothesis or candidate decision."""

    def __init__(
        self,
        hypothesis: Hypothesis,
        max_rounds: int = 4,
        approval_threshold: float = 0.6,
        dispute_protocol: Optional[DisputeProtocol] = None,
        belief_engine: Optional[BeliefRevisionEngine] = None,
        session_id: Optional[str] = None,
    ) -> None:
        if max_rounds < 1:
            raise DeliberationError("max_rounds must be at least 1")

        self.session_id: str = session_id or str(uuid4())
        self.hypothesis: Hypothesis = hypothesis
        self.max_rounds: int = max_rounds
        self.approval_threshold: float = approval_threshold
        self.current_round: int = 1
        self.state: SessionState = SessionState.OPEN

        self.belief_engine: BeliefRevisionEngine = belief_engine or BeliefRevisionEngine()
        self.dispute_protocol: DisputeProtocol = dispute_protocol or DisputeProtocol(self.belief_engine)

        self.votes: Dict[int, List[Vote]] = {1: []}
        self.history: List[Dict[str, str]] = []
        self._record_history("Session initialized in OPEN state.")

    def raise_dispute(
        self,
        agent_id: str,
        reason: str,
        *,
        dispute_id: str | None = None,
    ) -> Dispute:
        """Raise a dispute against the current hypothesis in session."""
        if self.state in (SessionState.DECISION_READY, SessionState.DEADLOCKED):
            raise DeliberationError(f"Cannot raise dispute in finished session state: {self.state}")

        dispute = self.dispute_protocol.raise_dispute(
            hypothesis=self.hypothesis,
            raised_by_agent_id=agent_id,
            reason=reason,
            dispute_id=dispute_id,
        )
        self.state = SessionState.IN_DISPUTE
        self._record_history(f"Dispute {dispute.dispute_id} raised by agent {agent_id}.")
        return dispute

    def resolve_dispute(
        self,
        dispute_id: str,
        evidence: Evidence,
        resolution_note: str,
    ) -> Dispute:
        """Resolve an active dispute using verified evidence."""
        dispute = self.dispute_protocol.resolve_with_evidence(
            dispute_id=dispute_id,
            hypothesis=self.hypothesis,
            evidence=evidence,
            resolution_note=resolution_note,
        )
        self._record_history(f"Dispute {dispute_id} resolved with evidence.")
        self._sync_state_after_dispute_update()
        return dispute

    def dismiss_dispute(self, dispute_id: str, justification: str) -> Dispute:
        """Dismiss an active dispute formally."""
        dispute = self.dispute_protocol.dismiss_dispute(
            dispute_id=dispute_id,
            justification=justification,
        )
        self._record_history(f"Dispute {dispute_id} formally dismissed.")
        self._sync_state_after_dispute_update()
        return dispute

    def cast_vote(self, agent_id: str, approved: bool, rationale: Optional[str] = None) -> Vote:
        """Cast a vote in the current deliberation round."""
        if self.state == SessionState.IN_DISPUTE:
            raise DeliberationError("Cannot vote while active disputes remain unresolved.")
        if self.state in (SessionState.DECISION_READY, SessionState.DEADLOCKED):
            raise DeliberationError(f"Cannot vote in terminal state: {self.state}")

        # Check duplicate vote in current round
        current_votes = self.votes.setdefault(self.current_round, [])
        if any(v.agent_id == agent_id for v in current_votes):
            raise DeliberationError(f"Agent {agent_id} has already voted in round {self.current_round}.")

        vote = Vote(
            agent_id=agent_id,
            hypothesis_id=self.hypothesis.hypothesis_id,
            approved=approved,
            rationale=rationale,
        )
        current_votes.append(vote)
        return vote

    def conclude_round(self) -> SessionState:
        """Conclude the current round, evaluating consensus or advancing rounds."""
        if self.state == SessionState.IN_DISPUTE:
            raise DeliberationError("Cannot conclude round with active disputes.")
        if self.state in (SessionState.DECISION_READY, SessionState.DEADLOCKED):
            return self.state

        current_votes = self.votes.get(self.current_round, [])
        if not current_votes:
            raise DeliberationError(f"Cannot conclude round {self.current_round} with zero votes.")

        total_votes = len(current_votes)
        approvals = sum(1 for v in current_votes if v.approved)
        approval_ratio = approvals / total_votes

        # Check if consensus/decision reached
        if approval_ratio >= self.approval_threshold and self.hypothesis.status != HypothesisStatus.REJECTED:
            self.state = SessionState.DECISION_READY
            self._record_history(
                f"Round {self.current_round} reached decision ({approvals}/{total_votes} approved, ratio={approval_ratio:.2f})."
            )
            return self.state

        # If not approved and we hit the max_rounds boundary -> DEADLOCKED
        if self.current_round >= self.max_rounds:
            self.state = SessionState.DEADLOCKED
            self._record_history(
                f"Max rounds ({self.max_rounds}) exceeded without consensus. Session marked DEADLOCKED."
            )
            return self.state

        # Otherwise advance to next round
        self.current_round += 1
        self.votes[self.current_round] = []
        self.state = SessionState.OPEN
        self._record_history(f"Advanced to round {self.current_round} (Open).")
        return self.state

    def _sync_state_after_dispute_update(self) -> None:
        """Transition back to OPEN if all disputes are resolved and not already terminal."""
        if not self.dispute_protocol.has_active_disputes(self.hypothesis.hypothesis_id):
            if self.state == SessionState.IN_DISPUTE:
                self.state = SessionState.OPEN

    def _record_history(self, message: str) -> None:
        self.history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "round": str(self.current_round),
            "state": self.state.value if isinstance(self.state, SessionState) else str(self.state),
            "message": message,
        })
