"""Unit tests for the Council execution gateway and Authority integration."""
from phase4.council.session import DeliberationSession, Dispute, SessionState
from phase4.council.integration import CouncilExecutionGateway


def test_council_integration_issues_grant_when_ready():
    gateway = CouncilExecutionGateway()
    session = DeliberationSession(session_id="sess-400", task_id="task-500", state=SessionState.DECISION_READY)
    
    grant = gateway.issue_execution_grant_if_ready(
        session=session,
        request_id="req-100",
        agent_id="agent-coder",
        target_resource="phase4/execution",
        action="execute_patch"
    )

    assert grant is not None
    assert grant.agent_identity == "agent-coder"
    assert grant.verified


def test_council_integration_denies_grant_when_not_ready():
    gateway = CouncilExecutionGateway()
    session = DeliberationSession(session_id="sess-401", task_id="task-501", state=SessionState.IN_DISPUTE)
    dispute = Dispute(
        dispute_id="disp-crit",
        hypothesis_id="h-99",
        challenger_role="SecuritySkeptic",
        argument="Unresolved authorization flaw",
        critical=True,
        resolved=False
    )
    session.raise_dispute(dispute)

    grant = gateway.issue_execution_grant_if_ready(
        session=session,
        request_id="req-101",
        agent_id="agent-coder",
        target_resource="phase4/execution",
        action="execute_patch"
    )

    assert grant is None
