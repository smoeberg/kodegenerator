from dataclasses import FrozenInstanceError

import pytest

from phase4.outcome.models import OutcomeRecord, OutcomeStatus
from phase4.planner.models import AgentActionProposal, ContinuationPolicy, PlanRequest, PlanStatus
from phase4.planner.engine import AgentPlanner


def make_outcome(status: OutcomeStatus, outcome_id: str = "outcome-1") -> OutcomeRecord:
    return OutcomeRecord(
        outcome_id=outcome_id,
        execution_id="exec-1",
        request_id="req-1",
        status=status,
        transitions=(),
        provenance_id="prov-1",
        produced_at="2026-08-08T00:00:00+00:00",
    )


def make_request(status=OutcomeStatus.FAILED, *, attempt=0, fingerprint="fp-1", parameters=(("b", "2"), ("a", "1"))):
    return PlanRequest(
        outcome=make_outcome(status),
        request_fingerprint=fingerprint,
        action="update",
        resource="resource-1",
        context_packet_id="ctx-1",
        parameters=parameters,
        attempt=attempt,
    )


def test_success_terminates_without_proposal():
    planner = AgentPlanner(ContinuationPolicy(max_retries=3))
    assert planner.plan(make_request(OutcomeStatus.SUCCEEDED)) is None


def test_unknown_outcome_fails_closed():
    planner = AgentPlanner(ContinuationPolicy(max_retries=3))
    assert planner.plan(make_request(OutcomeStatus.UNKNOWN)) is None


def test_failure_can_produce_retry_proposal():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    proposal = planner.plan(make_request())
    assert proposal is not None
    assert proposal.status is PlanStatus.PROPOSED
    assert proposal.attempt == 1


def test_retry_is_bounded():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    assert planner.plan(make_request(attempt=1)) is None


def test_rejected_is_retryable_by_default():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    proposal = planner.plan(make_request(OutcomeStatus.REJECTED))
    assert proposal is not None
    assert proposal.attempt == 1


def test_request_fingerprint_is_preserved_exactly():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    proposal = planner.plan(make_request(fingerprint="full-request-fingerprint"))
    assert proposal is not None
    assert proposal.request_fingerprint == "full-request-fingerprint"


def test_parameter_order_does_not_change_proposal_identity():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    first = planner.plan(make_request(parameters=(("a", "1"), ("b", "2"))))
    second = planner.plan(make_request(parameters=(("b", "2"), ("a", "1"))))
    assert first is not None and second is not None
    assert first.proposal_id == second.proposal_id
    assert first.parameters == (("a", "1"), ("b", "2"))


def test_duplicate_planning_is_idempotent():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    first = planner.plan(make_request())
    second = planner.plan(make_request())
    assert first is second


def test_proposal_is_not_executable():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    proposal = planner.plan(make_request())
    assert isinstance(proposal, AgentActionProposal)
    assert proposal.executable is False


def test_proposal_is_immutable():
    planner = AgentPlanner(ContinuationPolicy(max_retries=1))
    proposal = planner.plan(make_request())
    assert proposal is not None
    with pytest.raises(FrozenInstanceError):
        proposal.attempt = 99


def test_non_retryable_outcome_cannot_continue():
    planner = AgentPlanner(ContinuationPolicy(max_retries=3, retryable_statuses=(OutcomeStatus.FAILED,)))
    assert planner.plan(make_request(OutcomeStatus.REPLAYED)) is None


def test_zero_retry_policy_is_fail_closed():
    planner = AgentPlanner(ContinuationPolicy(max_retries=0))
    assert planner.plan(make_request()) is None
