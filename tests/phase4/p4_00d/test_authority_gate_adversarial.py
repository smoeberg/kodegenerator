<<<<<<< HEAD
"""P4-00D adversarial tests for the AI-3 -> AI-4 authority boundary.

The suite uses real AuthorityEngine and ExecutionEngine seams. Every rejected
attack must leave the adapter untouched and return no execution output.
=======
"""P4-00D adversarial contract for the post-P4-00C execution gate.

These tests attack the authority boundary without changing production code.
A passing test means the attempted bypass did not produce a successful execution.
The suite is intentionally independent of P4-00C's historical RED contract.
>>>>>>> origin/phase4/p4-00d-adversarial
"""
from __future__ import annotations

from dataclasses import replace
<<<<<<< HEAD
from datetime import datetime, timedelta, timezone

import pytest
=======
>>>>>>> origin/phase4/p4-00d-adversarial

from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest
from phase4.execution import ExecutionEngine, ExecutionRequest, ExecutionStatus


ACTION = "project.audit"
RESOURCE = "org-a/project-1"
<<<<<<< HEAD
ORGANIZATION = "org-a"
ACTOR = "actor-1"
AGENT = "agent-1"
CAPABILITY = "project.audit"
=======
AGENT = "agent-1"
>>>>>>> origin/phase4/p4-00d-adversarial
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
<<<<<<< HEAD
        organization_id=ORGANIZATION,
        actor_id=ACTOR,
        capability=CAPABILITY,
=======
>>>>>>> origin/phase4/p4-00d-adversarial
    )
    return replace(base, **changes)


def credentials():
    auth = authority()
<<<<<<< HEAD
    authority_request = AuthorityRequest(
=======
    ar = AuthorityRequest(
>>>>>>> origin/phase4/p4-00d-adversarial
        request_id="req-1",
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        requested_at="2026-08-10T00:00:00+00:00",
<<<<<<< HEAD
        parameters=(("fingerprint", "fp-1"),),
        organization_id=ORGANIZATION,
        actor_id=ACTOR,
        capability=CAPABILITY,
    )
    decision = auth.evaluate(authority_request)
=======
    )
    decision = auth.evaluate(ar)
>>>>>>> origin/phase4/p4-00d-adversarial
    grant = VerifiedAuthorityGrant.from_decision(decision)
    return auth, decision, grant


<<<<<<< HEAD
def assert_rejected_without_execution(
    grant,
    execution_request: ExecutionRequest | None = None,
):
    adapter = CountingAdapter()
    result = ExecutionEngine((adapter,)).execute(execution_request or request(), grant)
    assert result.status is ExecutionStatus.REJECTED
    assert result.output == ()
    assert adapter.calls == 0
    return result


def test_hand_constructed_grant_is_rejected():
=======
def test_forged_grant_is_rejected():
    engine = ExecutionEngine((CountingAdapter(),))
>>>>>>> origin/phase4/p4-00d-adversarial
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
<<<<<<< HEAD
        parameters=(("fingerprint", "fp-1"),),
        organization_id=ORGANIZATION,
        actor_id=ACTOR,
        capability=CAPABILITY,
        issuer_id="phase4.ai-3",
        grant_id="forged",
        issued_at="2026-08-10T00:00:00+00:00",
        expires_at="2099-08-10T00:05:00+00:00",
    )
    assert_rejected_without_execution(forged)


def test_signature_copied_from_a_real_grant_cannot_authenticate_a_forgery():
    _, _, genuine = credentials()
    forged = VerifiedAuthorityGrant(
        request_id=genuine.request_id,
        agent_identity=genuine.agent_identity,
        action=genuine.action,
        resource=genuine.resource,
        context_packet_id=genuine.context_packet_id,
        policy_id=genuine.policy_id,
        policy_version=genuine.policy_version,
        matched_rule_ids=genuine.matched_rule_ids,
        decision=genuine.decision,
        parameters=genuine.parameters,
        organization_id=genuine.organization_id,
        actor_id=genuine.actor_id,
        capability=genuine.capability,
        issuer_id=genuine.issuer_id,
        grant_id="forged-copy",
        issued_at=genuine.issued_at,
        expires_at=genuine.expires_at,
    )
    object.__setattr__(forged, "_signature", genuine._signature)
    assert_rejected_without_execution(forged)


def test_tampered_ai3_decision_cannot_become_a_grant():
    _, decision, _ = credentials()
    assert decision.provenance_verified is True
    tampered = replace(decision, policy_version="attacker-policy")
    assert tampered.provenance_verified is False
    with pytest.raises(ValueError, match="verified AI-3 provenance"):
        VerifiedAuthorityGrant.from_decision(tampered)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("request_id", "req-2"),
        ("resource", "org-b/project-1"),
        ("agent_identity", "agent-2"),
        ("context_packet_id", "context-2"),
        ("organization_id", "org-b"),
        ("actor_id", "actor-2"),
        ("capability", "project.delete"),
        ("parameters", (("fingerprint", "fp-evil"),)),
    ),
)
def test_grant_is_bound_to_every_supported_authority_claim(field, value):
    _, _, grant = credentials()
    assert_rejected_without_execution(grant, request(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("policy_version", "999"),
        ("issuer_id", "attacker"),
        ("expires_at", "2099-01-01T00:00:00+00:00"),
        ("grant_id", "attacker-grant"),
    ),
)
def test_signed_grant_metadata_tampering_is_rejected(field, value):
    _, _, grant = credentials()
    object.__setattr__(grant, field, value)
    assert_rejected_without_execution(grant)


def test_expired_grant_is_rejected_before_adapter_dispatch():
    _, decision, _ = credentials()
    past = datetime.now(timezone.utc) - timedelta(seconds=2)
    expired = VerifiedAuthorityGrant.from_decision(
        decision,
        ttl_seconds=1,
        now=past,
    )
    assert_rejected_without_execution(expired)


def test_future_dated_grant_is_rejected_before_adapter_dispatch():
    _, decision, _ = credentials()
    future = datetime.now(timezone.utc) + timedelta(minutes=1)
    not_yet_valid = VerifiedAuthorityGrant.from_decision(decision, now=future)
    assert_rejected_without_execution(not_yet_valid)


def test_grant_lifetime_cannot_exceed_the_security_contract():
    _, decision, _ = credentials()
    with pytest.raises(ValueError, match="ttl_seconds"):
        VerifiedAuthorityGrant.from_decision(decision, ttl_seconds=301)
=======
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
>>>>>>> origin/phase4/p4-00d-adversarial


def test_direct_engine_call_with_authority_decision_is_rejected():
    _, decision, _ = credentials()
<<<<<<< HEAD
    assert_rejected_without_execution(decision)
=======
    engine = ExecutionEngine((CountingAdapter(),))
    result = engine.execute(request(), decision)
    assert result.status is ExecutionStatus.REJECTED
>>>>>>> origin/phase4/p4-00d-adversarial


def test_replay_never_produces_a_second_success():
    _, _, grant = credentials()
<<<<<<< HEAD
    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,))
    first = engine.execute(request(), grant)
    second = engine.execute(request(), grant)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.status is ExecutionStatus.REPLAYED
    assert adapter.calls == 1


def test_reissuing_a_grant_cannot_bypass_request_idempotency():
    _, decision, first_grant = credentials()
    second_grant = VerifiedAuthorityGrant.from_decision(decision)
    assert first_grant.grant_id != second_grant.grant_id

    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,))
    first = engine.execute(request(), first_grant)
    second = engine.execute(request(), second_grant)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.status is ExecutionStatus.REPLAYED
    assert adapter.calls == 1
=======
    engine = ExecutionEngine((CountingAdapter(),))
    first = engine.execute(request(), grant)
    second = engine.execute(request(), grant)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert second.status is not ExecutionStatus.SUCCEEDED
>>>>>>> origin/phase4/p4-00d-adversarial
