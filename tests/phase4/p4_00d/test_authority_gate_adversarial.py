"""P4-00D adversarial contract for the post-P4-00C execution gate.

These tests attack the authority boundary without changing production code.
A passing test means the attempted bypass did not produce a successful execution.
The suite is intentionally independent of P4-00C's historical RED contract.
"""
from __future__ import annotations

from dataclasses import replace

from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest
from phase4.execution import ExecutionEngine, ExecutionRequest, ExecutionStatus


ACTION = "project.audit"
RESOURCE = "org-a/project-1"
AGENT = "agent-1"
CONTEXT = "context-1"


class CountingAdapter:
    adapter_id = "counting"
    action = ACTION

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, dispatch=None):
        self.calls += 1
        return type("Result", (), {"output": (("ok", "1"),)})()


def authority() -> AuthorityEngine:
    return AuthorityEngine(
        AuthorityPolicy(
            policy_id="policy-1",
            version="1",
            rules=(
                AuthorityRule(
                    rule_id="allow-1",
                    action=ACTION,
                    resource_pattern="org-a/*",
                    effect=Decision.ALLOW,
                    agent_identity=AGENT,
                ),
            ),
        )
    )


def request(**changes) -> ExecutionRequest:
    base = ExecutionRequest.create(
        request_id="req-1",
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        parameters={"fingerprint": "fp-1"},
        idempotency_key="idem-1",
    )
    return replace(base, **changes)


def credentials():
    auth = authority()
    ar = AuthorityRequest(
        request_id="req-1",
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        requested_at="2026-08-10T00:00:00+00:00",
    )
    decision = auth.evaluate(ar)
    grant = VerifiedAuthorityGrant.from_decision(decision)
    return auth, decision, grant


def test_forged_grant_is_rejected():
    engine = ExecutionEngine((CountingAdapter(),))
    forged = VerifiedAuthorityGrant(
        request_id="req-1",
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        policy_id="policy-1",
        policy_version="1",
        matched_rule_ids=("allow-1",),
        decision="allow",
    )
    result = engine.execute(request(), forged)
    assert result.status is ExecutionStatus.REJECTED


def test_stale_grant_cannot_be_reused_for_another_request():
    _, _, grant = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(request_id="req-2"), grant)
    assert result.status is ExecutionStatus.REJECTED


def test_wrong_resource_boundary_cannot_use_existing_grant():
    _, _, grant = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(resource="org-b/project-1"), grant)
    assert result.status is ExecutionStatus.REJECTED


def test_wrong_agent_cannot_use_existing_grant():
    _, _, grant = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(agent_identity="agent-2"), grant)
    assert result.status is ExecutionStatus.REJECTED


def test_wrong_context_cannot_use_existing_grant():
    _, _, grant = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(context_packet_id="context-2"), grant)
    assert result.status is ExecutionStatus.REJECTED


def test_parameter_fingerprint_mismatch_cannot_use_existing_grant():
    _, _, grant = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(parameters=(("fingerprint", "fp-evil"),)), grant)
    assert result.status is ExecutionStatus.REJECTED


def test_direct_engine_call_with_authority_decision_is_rejected():
    _, decision, _ = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(), decision)
    assert result.status is ExecutionStatus.REJECTED


def test_replay_never_produces_a_second_success():
    _, _, grant = credentials()
    engine = ExecutionEngine((CountingAdapter(),))
    first = engine.execute(request(), grant)
    second = engine.execute(request(), grant)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.status is not ExecutionStatus.SUCCEEDED
