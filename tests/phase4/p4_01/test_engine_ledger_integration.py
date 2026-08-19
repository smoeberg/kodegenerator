"""Engine integration with P4-01 replay ledger."""
from __future__ import annotations

from phase4.authority.engine import AuthorityEngine
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityPolicy, AuthorityRequest, AuthorityRule, Decision
from phase4.execution import (
    AdapterResult,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionStatus,
    InMemoryReplayLedger,
    StaticExecutionAdapter,
)
from phase4.execution.replay_ledger import ClaimOutcomeKind


def _grant(req: ExecutionRequest) -> VerifiedAuthorityGrant:
    authority_request = AuthorityRequest(
        request_id=req.request_id,
        agent_identity=req.agent_identity,
        action=req.action,
        resource=req.resource,
        context_packet_id=req.context_packet_id,
        requested_at="2026-08-18T00:00:00+00:00",
        parameters=req.parameters,
        organization_id=req.organization_id,
    )
    policy = AuthorityPolicy(
        policy_id="policy.demo",
        version="1",
        rules=(
            AuthorityRule(
                rule_id="rule.allow",
                action=req.action,
                resource_pattern=req.resource,
                effect=Decision.ALLOW,
            ),
        ),
    )
    return VerifiedAuthorityGrant.from_decision(AuthorityEngine(policy).evaluate(authority_request))


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        request_id="req-ledger",
        agent_identity="agent.demo",
        action="demo.read",
        resource="object/1",
        context_packet_id="ctx-1",
        parameters=(("k", "v"),),
        organization_id="org-demo",
    )


def test_shared_ledger_dedups_across_engine_instances():
    ledger = InMemoryReplayLedger()
    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    adapter = StaticExecutionAdapter("a", "demo.read", handler)
    engine_a = ExecutionEngine((adapter,), ledger=ledger)
    engine_b = ExecutionEngine((StaticExecutionAdapter("b", "demo.read", handler),), ledger=ledger)
    req = _request()
    first = engine_a.execute(req, _grant(req))
    second = engine_b.execute(req, _grant(req))
    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.status is ExecutionStatus.REPLAYED
    assert calls["n"] == 1


def test_in_flight_claim_rejects_without_second_adapter_call():
    ledger = InMemoryReplayLedger()
    ledger.try_claim("pre-seed")
    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    engine = ExecutionEngine((StaticExecutionAdapter("a", "demo.read", handler),), ledger=ledger)
    req = _request()
    grant = _grant(req)
    assert engine.execute(req, grant).status is ExecutionStatus.SUCCEEDED
    outcome = ledger.try_claim("manual-pending")
    assert outcome.kind is ClaimOutcomeKind.ACQUIRED
    assert ledger.try_claim("manual-pending").kind is ClaimOutcomeKind.IN_FLIGHT


def test_no_adapter_abandons_pending_so_later_registration_can_run():
    ledger = InMemoryReplayLedger()
    req = _request()
    grant = _grant(req)
    empty = ExecutionEngine(ledger=ledger)
    rejected = empty.execute(req, grant)
    assert rejected.status is ExecutionStatus.REJECTED

    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    engine = ExecutionEngine((StaticExecutionAdapter("a", "demo.read", handler),), ledger=ledger)
    result = engine.execute(req, grant)
    assert result.status is ExecutionStatus.SUCCEEDED
    assert calls["n"] == 1
