import pytest

from phase4.contracts import (
    Assignment,
    AssignmentState,
    Evidence,
    KnowledgeRecord,
    KnowledgeState,
    VerificationMode,
    VerificationPolicy,
)


def test_assignment_separates_agent_from_worker() -> None:
    assignment = Assignment(
        assignment_id="assignment-892",
        task_id="task-892",
        agent_id="agent-sec-014",
        state=AssignmentState.LEASED,
        attempt=1,
        worker_id="worker-07",
        lease_until="2026-08-12T10:00:00Z",
    )

    assert assignment.agent_id == "agent-sec-014"
    assert assignment.worker_id == "worker-07"
    assert assignment.state is AssignmentState.LEASED


def test_assignment_requires_worker_and_lease_together() -> None:
    with pytest.raises(ValueError):
        Assignment(
            assignment_id="assignment-1",
            task_id="task-1",
            agent_id="agent-1",
            worker_id="worker-1",
        )


def test_knowledge_record_is_immutable_and_versioned() -> None:
    evidence = Evidence(
        evidence_id="evidence-1",
        source="pytest",
        content_digest="sha256:abc",
    )
    record = KnowledgeRecord(
        record_id="record-1",
        subject="phase4",
        claim="the contract tests pass",
        evidence=(evidence,),
        state=KnowledgeState.PROPOSED,
        version=3,
        author_agent_id="agent-qa-01",
    )

    assert record.version == 3
    assert record.evidence[0].supports is True
    with pytest.raises(AttributeError):
        record.state = KnowledgeState.CONFIRMED  # type: ignore[misc]


def test_quorum_policy_requires_multiple_verifiers() -> None:
    policy = VerificationPolicy(
        mode=VerificationMode.QUORUM,
        quorum_size=3,
        risk_level=2,
        escalation_timeout_seconds=60,
    )

    assert policy.quorum_size == 3
    assert policy.risk_level == 2


def test_non_quorum_policy_cannot_request_quorum_size() -> None:
    with pytest.raises(ValueError):
        VerificationPolicy(mode=VerificationMode.DETERMINISTIC, quorum_size=2)


def test_confirmation_does_not_create_execution_authority() -> None:
    record = KnowledgeRecord(
        record_id="record-2",
        subject="execution",
        claim="the proposed change is verified",
        state=KnowledgeState.CONFIRMED,
        author_agent_id="agent-verifier-01",
    )

    # The contract deliberately contains no authority grant or execution token.
    assert not hasattr(record, "authority_grant")
