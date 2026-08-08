"""Contract tests for Phase 4 AI-4 Execution Engine."""
from dataclasses import FrozenInstanceError

import pytest

from phase4.authority.models import AuthorityDecision, Decision
from phase4.execution import (
    AdapterResult,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionStatus,
    StaticExecutionAdapter,
    execution_id_for,
)


def decision_for(request: ExecutionRequest, decision: Decision = Decision.ALLOW) -> AuthorityDecision:
    return AuthorityDecision(
        request_id=request.request_id,
        decision=decision,
        agent_identity=request.agent_identity,
        action=request.action,
        resource=request.resource,
        context_packet_id=request.context_packet_id,
        policy_id="policy.demo",
        policy_version="1",
        matched_rule_ids=("rule.allow",),
        reason="explicit test decision",
        evaluated_at="2026-08-08T12:00:00+00:00",
    )


def request(**overrides) -> ExecutionRequest:
    values = dict(
        request_id="req-001",
        agent_identity="agent.demo",
        action="demo.read",
        resource="object/42",
        context_packet_id="ctx-001",
        parameters=(("limit", "10"),),
    )
    values.update(overrides)
    return ExecutionRequest(**values)


def make_engine(counter=None) -> ExecutionEngine:
    if counter is None:
        counter = {"calls": 0}

    def handler(req):
        counter["calls"] += 1
        return AdapterResult(output=(("resource", req.resource),))

    return ExecutionEngine((StaticExecutionAdapter("adapter.demo.read", "demo.read", handler),))


def test_explicit_allow_reaches_registered_adapter():
    counter = {"calls": 0}
    engine = make_engine(counter)
    req = request()
    result = engine.execute(req, decision_for(req))
    assert result.status is ExecutionStatus.SUCCEEDED
    assert result.succeeded
    assert result.adapter_id == "adapter.demo.read"
    assert result.output == (("resource", "object/42"),)
    assert counter["calls"] == 1


def test_missing_authority_fails_closed():
    counter = {"calls": 0}
    engine = make_engine(counter)
    result = engine.execute(request(), None)
    assert result.status is ExecutionStatus.REJECTED
    assert "missing authority" in result.error
    assert counter["calls"] == 0


def test_deny_never_reaches_adapter():
    counter = {"calls": 0}
    engine = make_engine(counter)
    req = request()
    result = engine.execute(req, decision_for(req, Decision.DENY))
    assert result.status is ExecutionStatus.REJECTED
    assert "not ALLOW" in result.error
    assert counter["calls"] == 0


def test_deny_cannot_replay_a_previous_allow():
    counter = {"calls": 0}
    engine = make_engine(counter)
    req = request()
    allowed = engine.execute(req, decision_for(req, Decision.ALLOW))
    denied = engine.execute(req, decision_for(req, Decision.DENY))
    assert allowed.status is ExecutionStatus.SUCCEEDED
    assert denied.status is ExecutionStatus.REJECTED
    assert counter["calls"] == 1


@pytest.mark.parametrize("field", ["request_id", "agent_identity", "action", "resource", "context_packet_id"])
def test_security_binding_mismatch_is_rejected(field):
    counter = {"calls": 0}
    engine = make_engine(counter)
    req = request()
    values = {
        "request_id": "req-other",
        "agent_identity": "agent.other",
        "action": "demo.write",
        "resource": "object/99",
        "context_packet_id": "ctx-other",
    }
    tampered = request(**{field: values[field]})
    result = engine.execute(tampered, decision_for(req))
    assert result.status is ExecutionStatus.REJECTED
    assert counter["calls"] == 0


def test_no_adapter_is_rejected_without_inventing_execution():
    req = request()
    result = ExecutionEngine().execute(req, decision_for(req))
    assert result.status is ExecutionStatus.REJECTED
    assert "no execution adapter" in result.error


def test_same_authorized_request_is_idempotent():
    counter = {"calls": 0}
    engine = make_engine(counter)
    req = request()
    decision = decision_for(req)
    first = engine.execute(req, decision)
    second = engine.execute(req, decision)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.status is ExecutionStatus.REPLAYED
    assert second.execution_id == first.execution_id
    assert counter["calls"] == 1


def test_adapter_exception_is_audited_as_failure():
    def failing(_):
        raise RuntimeError("backend unavailable")
    engine = ExecutionEngine((StaticExecutionAdapter("adapter.fail", "demo.read", failing),))
    req = request()
    result = engine.execute(req, decision_for(req))
    assert result.status is ExecutionStatus.FAILED
    assert result.error == "RuntimeError: backend unavailable"
    assert engine.audit_trail()[-1] == result


def test_failed_execution_is_not_silently_retried():
    counter = {"calls": 0}
    def failing(_):
        counter["calls"] += 1
        raise RuntimeError("temporary failure")
    engine = ExecutionEngine((StaticExecutionAdapter("adapter.fail", "demo.read", failing),))
    req = request()
    decision = decision_for(req)
    first = engine.execute(req, decision)
    second = engine.execute(req, decision)
    assert first.status is ExecutionStatus.FAILED
    assert second.status is ExecutionStatus.REPLAYED
    assert counter["calls"] == 1


def test_execution_result_is_immutable():
    req = request()
    result = make_engine().execute(req, decision_for(req))
    with pytest.raises(FrozenInstanceError):
        result.status = ExecutionStatus.FAILED


def test_execution_request_is_immutable():
    req = request()
    with pytest.raises(FrozenInstanceError):
        req.action = "demo.write"


def test_execution_id_is_deterministic():
    req = request()
    decision = decision_for(req)
    assert execution_id_for(req, decision) == execution_id_for(req, decision)


def test_parameter_order_does_not_change_execution_identity():
    req1 = request(parameters=(("a", "1"), ("b", "2")))
    req2 = request(parameters=(("b", "2"), ("a", "1")))
    assert execution_id_for(req1, decision_for(req1)) == execution_id_for(req2, decision_for(req2))


def test_policy_version_is_bound_into_execution_identity():
    req = request()
    decision1 = decision_for(req)
    decision2 = AuthorityDecision(
        request_id=req.request_id,
        decision=Decision.ALLOW,
        agent_identity=req.agent_identity,
        action=req.action,
        resource=req.resource,
        context_packet_id=req.context_packet_id,
        policy_id="policy.demo",
        policy_version="2",
        matched_rule_ids=("rule.allow",),
        reason="explicit test decision",
        evaluated_at="2026-08-08T12:00:00+00:00",
    )
    assert execution_id_for(req, decision1) != execution_id_for(req, decision2)


def test_audit_trail_contains_rejected_and_successful_attempts():
    engine = make_engine()
    req = request()
    denied = engine.execute(req, decision_for(req, Decision.DENY))
    allowed = engine.execute(req, decision_for(req))
    assert tuple(record.status for record in engine.audit_trail()) == (
        ExecutionStatus.REJECTED,
        ExecutionStatus.SUCCEEDED,
    )
    assert engine.audit_trail()[0] == denied
    assert engine.audit_trail()[1] == allowed


def test_duplicate_action_registration_is_rejected():
    first = StaticExecutionAdapter("adapter.one", "demo.read", lambda _: {})
    second = StaticExecutionAdapter("adapter.two", "demo.read", lambda _: {})
    engine = ExecutionEngine((first,))
    with pytest.raises(ValueError, match="already registered"):
        engine.register_adapter(second)


def test_adapter_receives_bounded_execution_request():
    observed = {}
    def handler(req):
        observed["type"] = type(req)
        observed["action"] = req.action
        return {}
    engine = ExecutionEngine((StaticExecutionAdapter("adapter.demo", "demo.read", handler),))
    req = request()
    result = engine.execute(req, decision_for(req))
    assert result.succeeded
    assert observed == {"type": ExecutionRequest, "action": "demo.read"}


def test_audit_snapshot_is_immutable_tuple():
    engine = make_engine()
    req = request()
    engine.execute(req, decision_for(req))
    snapshot = engine.audit_trail()
    assert isinstance(snapshot, tuple)
    with pytest.raises(AttributeError):
        snapshot.append("bad")
