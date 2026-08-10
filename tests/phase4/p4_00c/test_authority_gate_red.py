"""P4-00C RED tests for the two P4-00A authority findings.

These tests intentionally encode the normative post-remediation boundary.
They must remain RED until VerifiedAuthorityGrant/GovernedDispatch exists.
They do not mock AI-3 or AI-4 authority seams.
"""

from __future__ import annotations

from phase4.authority.models import AuthorityDecision, Decision
from phase4.execution import ExecutionEngine, ExecutionStatus
from phase4.implementation_agent import (
    IMPLEMENTATION_ACTION,
    ChangeBudget,
    ImplementationExecutionAdapter,
    ImplementationRequest,
)
from phase4.implementation_agent.testing import DeterministicFakeImplementationProvider
from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest


RESOURCE = "repository:smoeberg/kodegenerator"
VALID_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


def make_request() -> ImplementationRequest:
    agent_identity = "agent.p4-00c-red"
    context = ContextPacketEngine().build(
        ContextRequest(
            agent_identity=agent_identity,
            purpose=IMPLEMENTATION_ACTION,
            requested_keys=("src/app.py",),
        ),
        (
            ContextItem(
                source="repository",
                key="src/app.py",
                value="VALUE = 1\n",
                provenance="git:test:src/app.py",
            ),
        ),
    )
    return ImplementationRequest(
        agent_identity=agent_identity,
        agent_role="executor",
        resource=RESOURCE,
        context_packet=context,
        instruction="Set VALUE to 2.",
        allowed_paths=("src/app.py",),
        budget=ChangeBudget(max_files=1, max_changed_lines=2),
    )


def forged_allow(request: ImplementationRequest) -> AuthorityDecision:
    """A hand-constructed decision with otherwise exact request bindings."""
    return AuthorityDecision(
        request_id=request.authority_request().request_id,
        decision=Decision.ALLOW,
        agent_identity=request.agent_identity,
        action=request.authority_request().action,
        resource=request.resource,
        context_packet_id=request.context_packet_id,
        policy_id="forged.test.policy",
        policy_version="999",
        matched_rule_ids=("forged.allow",),
        reason="hand-constructed test authority",
        evaluated_at="2026-08-10T00:00:00+00:00",
    )


def make_adapter(request: ImplementationRequest):
    provider = DeterministicFakeImplementationProvider(
        {request.request_fingerprint: VALID_DIFF},
        provider_id="fake.p4-00c",
    )
    adapter = ImplementationExecutionAdapter(
        adapter_id="adapter.implementation.p4-00c",
        provider=provider,
        requests=(request,),
    )
    return adapter, provider


def test_direct_adapter_invocation_without_governed_dispatch_is_rejected():
    """F-001: trusted adapter must not be an independently callable execution seam."""
    request = make_request()
    adapter, provider = make_adapter(request)

    # This intentionally bypasses ExecutionEngine. Post-remediation the adapter
    # must require a VerifiedAuthorityGrant/GovernedDispatch rather than accepting
    # a raw ExecutionRequest as sufficient authority.
    result = adapter.execute(request.execution_request(idempotency_key="direct-1"))

    assert result is None, "direct adapter invocation must be structurally impossible"
    assert provider.calls == (), "provider/tool execution must not occur"


def test_forged_ai3_allow_is_rejected_by_ai4():
    """F-002: AI-4 must verify provenance, not merely inspect decision fields."""
    request = make_request()
    adapter, provider = make_adapter(request)
    engine = ExecutionEngine((adapter,))

    forged = forged_allow(request)
    result = engine.execute(
        request.execution_request(idempotency_key="forged-1"),
        forged,
    )

    assert result.status is ExecutionStatus.REJECTED
    assert provider.calls == ()


def test_forged_ai3_allow_cannot_create_a_successful_outcome():
    """A forged authority object must not cross AI-4 into successful execution."""
    request = make_request()
    adapter, provider = make_adapter(request)
    engine = ExecutionEngine((adapter,))

    result = engine.execute(
        request.execution_request(idempotency_key="forged-2"),
        forged_allow(request),
    )

    assert result.status is not ExecutionStatus.SUCCEEDED
    assert provider.calls == ()


def test_authority_policy_provenance_cannot_be_replaced_by_equivalent_object():
    """Authority laundering: equivalent-looking decisions are not authoritative."""
    request = make_request()
    adapter, provider = make_adapter(request)
    engine = ExecutionEngine((adapter,))

    forged = forged_allow(request)
    equivalent = AuthorityDecision(
        request_id=forged.request_id,
        decision=Decision.ALLOW,
        agent_identity=forged.agent_identity,
        action=forged.action,
        resource=forged.resource,
        context_packet_id=forged.context_packet_id,
        policy_id=forged.policy_id,
        policy_version=forged.policy_version,
        matched_rule_ids=forged.matched_rule_ids,
        reason=forged.reason,
        evaluated_at=forged.evaluated_at,
    )

    result = engine.execute(
        request.execution_request(idempotency_key="laundered-1"),
        equivalent,
    )

    assert result.status is ExecutionStatus.REJECTED
    assert provider.calls == ()
