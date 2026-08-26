"""Role orchestration for the Dialectical Council deliberation cycle."""
from __future__ import annotations

from typing import List
from phase4.council.session import DeliberationSession, Dispute, SessionState
from phase4.epistemics.models import Hypothesis


class DialecticalCouncilOrchestrator:
    """Orchestrates multi-agent roles (Proposer, Architect, Security Skeptic) in deliberation."""

    @staticmethod
    def evaluate_deliberation(session: DeliberationSession) -> SessionState:
        """Evaluate current deliberation state based on hypotheses and active disputes."""
        if not session.hypotheses:
            session.state = SessionState.OPEN
            return session.state

        open_criticals = [d for d in session.disputes if d.critical and not d.resolved]
        
        if open_criticals:
            if session.round_count >= session.max_rounds:
                session.state = SessionState.DEADLOCKED
            else:
                session.state = SessionState.IN_DISPUTE
        else:
            session.state = SessionState.DECISION_READY

        return session.state
