"""Unit tests for the Dialectical Council deliberation session and dispute protocol."""
from phase4.council.session import DeliberationSession, Dispute, SessionState
from phase4.council.deliberation import DialecticalCouncilOrchestrator
from phase4.epistemics.models import Hypothesis


def test_council_session_lifecycle():
    session = DeliberationSession(session_id="sess-1", task_id="task-200")
    assert session.state == SessionState.OPEN

    h = Hypothesis(hypothesis_id="h-10", task_id="task-200", statement="Use OAuth2 with JWT")
    session.add_hypothesis(h)

    dispute = Dispute(
        dispute_id="disp-1",
        hypothesis_id="h-10",
        challenger_role="SecuritySkeptic",
        argument="Token revocation lacks central blacklist check",
        critical=True
    )
    session.raise_dispute(dispute)
    assert session.state == SessionState.IN_DISPUTE
    assert len(session.disputes) == 1

    session.resolve_dispute("disp-1", resolution_note="Added Redis token revocation blacklist check")
    assert session.state == SessionState.DECISION_READY


def test_council_deadlock_on_max_rounds():
    session = DeliberationSession(session_id="sess-2", task_id="task-201", max_rounds=2)
    h = Hypothesis(hypothesis_id="h-11", task_id="task-201", statement="Monolithic refactor")
    session.add_hypothesis(h)
    dispute = Dispute(
        dispute_id="disp-2",
        hypothesis_id="h-11",
        challenger_role="Architect",
        argument="Unresolved circular dependency",
        critical=True
    )
    session.raise_dispute(dispute)
    
    session.advance_round()
    session.advance_round()
    
    DialecticalCouncilOrchestrator.evaluate_deliberation(session)
    assert session.state == SessionState.DEADLOCKED
