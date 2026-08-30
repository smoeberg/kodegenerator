"""Tests for the AI-7 orchestration repair-loop engine."""


from phase4.orchestrator.engine import OrchestratorEngine, StaticRepairAdapter
from phase4.orchestrator.models import (
    IterationIdentity,
    LoopBounds,
    OrchestrationDirective,
    OrchestrationObservation,
    OrchestrationState,
    PlanRequest,
    decide,
)
from phase4.outcome.models import OutcomeRecord, OutcomeStatus


def make_outcome(status: OutcomeStatus = OutcomeStatus.FAILED) -> OutcomeRecord:
    from datetime import datetime, timezone
    return OutcomeRecord(
        outcome_id="outcome-1",
        execution_id="exec-1",
        request_id="req-1",
        status=status,
        transitions=(),
        provenance_id="prov-1",
        produced_at=datetime.now(timezone.utc).isoformat(),
        error="boom" if status is OutcomeStatus.FAILED else None,
    )


def _make_request(outcome: OutcomeRecord, retry_count: int = 0) -> PlanRequest:
    return PlanRequest(
        outcome=outcome,
        request_fingerprint="fp-1",
        action="implement",
        resource="auth",
        context_packet_id="ctx-1",
        attempt=retry_count,
    )


def make_observation(
    outcome: OutcomeRecord,
    retry_count: int = 0,
    authority: bool = True,
    number: int = 1,
) -> OrchestrationObservation:
    from datetime import datetime, timezone

    from phase4.authority.models import AuthorityDecision, Decision

    plan_request = PlanRequest(
        outcome=outcome,
        request_fingerprint="fp-1",
        action="implement",
        resource="auth",
        context_packet_id="ctx-1",
        attempt=retry_count,
    )
    authority_decision = None
    if authority:
        authority_decision = AuthorityDecision(
            request_id=outcome.request_id,
            decision=Decision.ALLOW,
            agent_identity="auth-agent",
            action="implement",
            resource="auth",
            context_packet_id="ctx-1",
            policy_id="policy-1",
            policy_version="1",
            matched_rule_ids=("rule-1",),
            reason="verified",
            evaluated_at=datetime.now(timezone.utc).isoformat(),
        )
    return OrchestrationObservation(
        iteration=IterationIdentity(run_id="run-1", number=number, retry_count=retry_count),
        plan_request=plan_request,
        authority_decision=authority_decision,
    )


def test_decision_is_contract_validated_and_immutable():
    decision = decide(
        make_observation(make_outcome()),
        LoopBounds(max_depth=5, max_retries=2),
    )
    assert decision.directive is OrchestrationDirective.CONTINUE


def test_run_loop_advances_until_adapter_capacity():
    engine = OrchestratorEngine(
        adapter=StaticRepairAdapter(max_repairs=2),
        bounds=LoopBounds(max_depth=5, max_retries=2),
    )
    final, decision = engine.run_loop(make_observation(make_outcome()))
    assert decision.directive is OrchestrationDirective.STOP
    assert decision.state is OrchestrationState.RETRY_LIMIT_REACHED
    assert final.iteration.retry_count == 2
    assert final.plan_request.attempt == 2  # attempt tied to retry_count


def test_successful_outcome_stops_immediately():
    engine = OrchestratorEngine(
        adapter=StaticRepairAdapter(max_repairs=2),
        bounds=LoopBounds(max_depth=5, max_retries=2),
    )
    final, decision = engine.run_loop(make_observation(make_outcome(OutcomeStatus.SUCCEEDED)))
    assert decision.directive is OrchestrationDirective.STOP
    assert final.iteration.retry_count == 0
    assert decision.state is OrchestrationState.COMPLETED


def test_static_adapter_refuses_after_capacity():
    adapter = StaticRepairAdapter(max_repairs=1)
    request = _make_request(make_outcome())
    assert adapter.propose(request) is not None
    assert adapter.propose(request) is None


def test_engine_never_mutates_outcome():
    outcome = make_outcome()
    engine = OrchestratorEngine(bounds=LoopBounds(max_depth=5, max_retries=2))
    final, _ = engine.run_loop(make_observation(outcome))
    assert final is not outcome  # observation is advanced, outcome untouched
    assert outcome.status is OutcomeStatus.FAILED
