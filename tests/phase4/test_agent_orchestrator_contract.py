"""Contract tests for the Phase 4 AI-7 orchestration boundary."""
from dataclasses import FrozenInstanceError, replace

import pytest

import phase4.orchestrator as orchestrator
from phase4.authority.models import AuthorityDecision, Decision
from phase4.outcome.models import OutcomeRecord, OutcomeStatus
from phase4.planner.models import PlanRequest
from phase4.orchestrator.models import (
    DecisionReason,
    IterationIdentity,
    LoopBounds,
    OrchestrationDecision,
    OrchestrationDirective,
    OrchestrationObservation,
    OrchestrationState,
    PlannerHandoff,
    decide,
)


def make_outcome(
    status: OutcomeStatus = OutcomeStatus.FAILED,
    *,
    outcome_id: str = "outcome-1",
    request_id: str = "request-1",
) -> OutcomeRecord:
    return OutcomeRecord(
        outcome_id=outcome_id,
        execution_id="execution-1",
        request_id=request_id,
        status=status,
        transitions=(),
        provenance_id="provenance-1",
        produced_at="2026-08-08T00:00:00+00:00",
    )


def make_authority(
    decision: Decision = Decision.ALLOW,
    *,
    request_id: str = "request-1",
) -> AuthorityDecision:
    return AuthorityDecision(
        request_id=request_id,
        decision=decision,
        agent_identity="agent-1",
        action="update",
        resource="resource-1",
        context_packet_id="context-1",
        policy_id="policy-1",
        policy_version="1",
        matched_rule_ids=("rule-1",),
        reason="explicit test decision",
        evaluated_at="2026-08-08T00:00:00+00:00",
    )


def make_plan_request(
    status: OutcomeStatus = OutcomeStatus.FAILED,
    *,
    attempt: int = 0,
    outcome_id: str = "outcome-1",
) -> PlanRequest:
    return PlanRequest(
        outcome=make_outcome(status, outcome_id=outcome_id),
        request_fingerprint="request-fingerprint-1",
        action="update",
        resource="resource-1",
        context_packet_id="context-1",
        parameters=(("key", "value"),),
        attempt=attempt,
    )


def make_observation(
    status: OutcomeStatus = OutcomeStatus.FAILED,
    *,
    number: int = 1,
    retry_count: int = 0,
    authority: AuthorityDecision | None = None,
    processed_outcome_ids=(),
    outcome_id: str = "outcome-1",
) -> OrchestrationObservation:
    return OrchestrationObservation(
        iteration=IterationIdentity("run-1", number=number, retry_count=retry_count),
        plan_request=make_plan_request(status, attempt=retry_count, outcome_id=outcome_id),
        authority_decision=authority if authority is not None else make_authority(),
        processed_outcome_ids=processed_outcome_ids,
    )


def test_failure_continues_only_through_ai6():
    observation = make_observation()
    decision = decide(observation, LoopBounds(max_depth=3, max_retries=2))

    assert decision.directive is OrchestrationDirective.CONTINUE
    assert decision.state is OrchestrationState.ACTIVE
    assert decision.reason is DecisionReason.PLANNING_REQUIRED
    assert decision.handoff is not None
    assert decision.handoff.boundary == "AI-6"
    assert decision.handoff.plan_request is observation.plan_request
    assert decision.outcome is observation.outcome


def test_run_and_iteration_correlation_are_preserved_in_handoff():
    observation = make_observation()
    decision = decide(observation, LoopBounds(max_depth=2, max_retries=1))

    assert decision.run_id == "run-1"
    assert decision.iteration_id == observation.iteration.iteration_id
    assert decision.handoff is not None
    assert decision.handoff.run_id == decision.run_id
    assert decision.handoff.iteration_id == decision.iteration_id


def test_iteration_identity_is_deterministic_and_run_scoped():
    first = IterationIdentity("run-1", number=2, retry_count=1)
    same = IterationIdentity("run-1", number=2, retry_count=1)
    other_run = IterationIdentity("run-2", number=2, retry_count=1)

    assert first.iteration_id == same.iteration_id
    assert first.iteration_id != other_run.iteration_id


@pytest.mark.parametrize(
    ("number", "retry_count"),
    ((0, 0), (1, 1), (2, 0), (2, -1)),
)
def test_iteration_counters_cannot_be_reset_independently(number, retry_count):
    with pytest.raises(ValueError):
        IterationIdentity("run-1", number=number, retry_count=retry_count)


@pytest.mark.parametrize("run_id", ("", "   "))
def test_run_id_must_be_non_empty(run_id):
    with pytest.raises(ValueError):
        IterationIdentity(run_id)


def test_plan_attempt_must_match_iteration_retry_count():
    with pytest.raises(ValueError, match="plan attempt"):
        OrchestrationObservation(
            iteration=IterationIdentity("run-1", number=2, retry_count=1),
            plan_request=make_plan_request(attempt=0),
            authority_decision=make_authority(),
        )


@pytest.mark.parametrize(
    ("max_depth", "max_retries", "error"),
    ((0, 0, ValueError), (1, -1, ValueError), (True, 0, TypeError), (1, False, TypeError)),
)
def test_loop_bounds_are_explicit_finite_integers(max_depth, max_retries, error):
    with pytest.raises(error):
        LoopBounds(max_depth=max_depth, max_retries=max_retries)


def test_loop_depth_is_bounded_before_ai6_handoff():
    decision = decide(
        make_observation(),
        LoopBounds(max_depth=1, max_retries=10),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.DEPTH_LIMIT_REACHED
    assert decision.terminal is True
    assert decision.handoff is None


def test_retries_are_bounded_before_ai6_handoff():
    decision = decide(
        make_observation(),
        LoopBounds(max_depth=10, max_retries=0),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.RETRY_LIMIT_REACHED
    assert decision.terminal is True
    assert decision.handoff is None


def test_success_is_a_terminal_stop():
    decision = decide(
        make_observation(OutcomeStatus.SUCCEEDED),
        LoopBounds(max_depth=3, max_retries=2),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.COMPLETED
    assert decision.reason is DecisionReason.OUTCOME_SUCCEEDED
    assert decision.terminal is True


def test_denied_authority_terminates_without_planning():
    observation = make_observation(
        OutcomeStatus.REJECTED,
        authority=make_authority(Decision.DENY),
    )
    decision = decide(observation, LoopBounds(max_depth=3, max_retries=2))

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.AUTHORITY_DENIED
    assert decision.reason is DecisionReason.AUTHORITY_DENIED
    assert decision.handoff is None


def test_missing_authority_fails_closed():
    observation = OrchestrationObservation(
        iteration=IterationIdentity("run-1"),
        plan_request=make_plan_request(),
        authority_decision=None,
    )
    decision = decide(observation, LoopBounds(max_depth=3, max_retries=2))

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.AUTHORITY_UNVERIFIED
    assert decision.handoff is None


def test_unknown_outcome_fails_closed():
    decision = decide(
        make_observation(OutcomeStatus.UNKNOWN),
        LoopBounds(max_depth=3, max_retries=2),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.OUTCOME_UNKNOWN
    assert decision.reason is DecisionReason.OUTCOME_UNKNOWN
    assert decision.handoff is None


def test_duplicate_outcome_cannot_create_another_handoff():
    observation = make_observation(processed_outcome_ids=("outcome-1",))
    decision = decide(observation, LoopBounds(max_depth=3, max_retries=2))

    assert observation.duplicate_outcome is True
    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.DUPLICATE_OUTCOME
    assert decision.reason is DecisionReason.DUPLICATE_OUTCOME
    assert decision.handoff is None


def test_replayed_outcome_cannot_continue():
    decision = decide(
        make_observation(OutcomeStatus.REPLAYED),
        LoopBounds(max_depth=3, max_retries=2),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.DUPLICATE_OUTCOME
    assert decision.reason is DecisionReason.REPLAYED_OUTCOME


def test_processed_outcome_history_cannot_itself_contain_duplicates():
    with pytest.raises(ValueError, match="must be unique"):
        make_observation(processed_outcome_ids=("outcome-old", "outcome-old"))


def test_authority_decision_must_be_bound_to_the_outcome_request():
    with pytest.raises(ValueError, match="request_id"):
        OrchestrationObservation(
            iteration=IterationIdentity("run-1"),
            plan_request=make_plan_request(),
            authority_decision=make_authority(request_id="different-request"),
        )


@pytest.mark.parametrize("field", ("action", "resource", "context_packet_id"))
def test_authority_subject_must_match_the_planning_subject(field):
    authority = replace(make_authority(), **{field: "different-value"})
    with pytest.raises(ValueError, match=field):
        OrchestrationObservation(
            iteration=IterationIdentity("run-1"),
            plan_request=make_plan_request(),
            authority_decision=authority,
        )


def test_unrecognized_authority_value_fails_closed():
    authority = replace(make_authority(), decision="unexpected")
    decision = decide(
        make_observation(authority=authority),
        LoopBounds(max_depth=3, max_retries=2),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.AUTHORITY_UNVERIFIED
    assert decision.reason is DecisionReason.AUTHORITY_INVALID
    assert decision.handoff is None


def test_unrecognized_outcome_value_fails_closed():
    decision = decide(
        make_observation("unexpected"),
        LoopBounds(max_depth=3, max_retries=2),
    )

    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.OUTCOME_UNKNOWN
    assert decision.reason is DecisionReason.OUTCOME_UNKNOWN
    assert decision.handoff is None


def test_all_non_active_states_are_terminal():
    assert OrchestrationState.ACTIVE.terminal is False
    assert all(
        state.terminal
        for state in OrchestrationState
        if state is not OrchestrationState.ACTIVE
    )


def test_unknown_cannot_be_relabelled_as_continue():
    observation = make_observation(OutcomeStatus.UNKNOWN)
    handoff = PlannerHandoff(
        run_id=observation.run_id,
        iteration_id=observation.iteration.iteration_id,
        plan_request=observation.plan_request,
    )

    with pytest.raises(ValueError, match="violates"):
        OrchestrationDecision(
            observation=observation,
            bounds=LoopBounds(max_depth=3, max_retries=2),
            directive=OrchestrationDirective.CONTINUE,
            state=OrchestrationState.ACTIVE,
            reason=DecisionReason.PLANNING_REQUIRED,
            handoff=handoff,
        )


def test_ai7_cannot_execute_or_issue_authority():
    decision = decide(
        make_observation(),
        LoopBounds(max_depth=3, max_retries=2),
    )
    assert decision.handoff is not None

    assert decision.executable is False
    assert decision.authoritative is False
    assert decision.handoff.executable is False
    assert decision.handoff.authoritative is False
    assert not hasattr(decision, "execute")
    assert not hasattr(decision, "authorize")
    assert "ExecutionRequest" not in orchestrator.__all__
    assert "AuthorityRequest" not in orchestrator.__all__


def test_ai7_preserves_immutable_outcome_and_plan_request():
    observation = make_observation()
    decision = decide(observation, LoopBounds(max_depth=3, max_retries=2))

    assert decision.outcome is observation.plan_request.outcome
    assert decision.handoff is not None
    assert decision.handoff.plan_request is observation.plan_request
    with pytest.raises(FrozenInstanceError):
        decision.outcome.status = OutcomeStatus.SUCCEEDED
    with pytest.raises(FrozenInstanceError):
        decision.handoff.plan_request.attempt = 99
    with pytest.raises(FrozenInstanceError):
        decision.directive = OrchestrationDirective.STOP
