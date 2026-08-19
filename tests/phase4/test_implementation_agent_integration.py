"""One complete Phase 4B-1 reference flow through AI-1 to AI-5."""

<<<<<<< HEAD
from phase4.agent_registry import (
    AgentRegistry,
    AgentRole,
    AgentVersion,
    Capability,
)
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority import (
    AuthorityEngine,
    AuthorityPolicy,
    AuthorityRule,
    Decision,
)
=======
from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
>>>>>>> origin/phase4/p4-08-02-safe-patch-apply-v3
from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionEngine, ExecutionStatus
from phase4.implementation_agent import IMPLEMENTATION_ACTION, ChangeBudget, ImplementationExecutionAdapter, ImplementationRequest
from phase4.implementation_agent.testing import DeterministicFakeImplementationProvider
from phase4.outcome.engine import OutcomeEngine
from phase4.outcome.models import OutcomeStatus


def test_registered_agent_produces_governed_patch_outcome_through_ai1_to_ai5():
    registry = AgentRegistry()
    agent = registry.register(
        agent_type="implementation-agent",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.EXECUTOR,
        capabilities=(Capability.create(IMPLEMENTATION_ACTION, AgentVersion(1, 0, 0)),),
        actor="phase4b-bootstrap",
    )
    context_packet = ContextPacketEngine().build(
        ContextRequest(agent_identity=str(agent.identity), purpose=IMPLEMENTATION_ACTION, requested_keys=("src/calculator.py", "acceptance"), max_items=2, max_bytes=4_096),
        (
            ContextItem(source="repository", key="src/calculator.py", value="def add(left, right):\n    return left - right\n", provenance="git:39a44a7:src/calculator.py"),
            ContextItem(source="requirements", key="acceptance", value="add(2, 3) returns 5", provenance="requirement:REQ-CALC-1"),
        ),
    )
    implementation_request = ImplementationRequest(
        agent_identity=str(agent.identity), agent_role=agent.role.value, resource="repository:smoeberg/kodegenerator",
        context_packet=context_packet, instruction="Correct add so it returns the sum of its arguments.",
        allowed_paths=("src/calculator.py",), budget=ChangeBudget(max_files=1, max_changed_lines=2),
    )
    authority_request = implementation_request.authority_request()
    authority = AuthorityEngine(AuthorityPolicy(
        policy_id="policy.phase4b.implementation", version="1", rules=(AuthorityRule(
            rule_id="allow-bounded-patch-proposal", action=IMPLEMENTATION_ACTION,
            resource_pattern="repository:smoeberg/kodegenerator", effect=Decision.ALLOW,
            agent_identity=str(agent.identity), agent_role=AgentRole.EXECUTOR.value,
            required_context=tuple(sorted(implementation_request.authority_context().items())),
        ),),
    )).evaluate(authority_request)
    diff = """diff --git a/src/calculator.py b/src/calculator.py
--- a/src/calculator.py
+++ b/src/calculator.py
@@ -1,2 +1,2 @@
 def add(left, right):
-    return left - right
+    return left + right
"""
<<<<<<< HEAD
    provider = DeterministicFakeImplementationProvider(
        {implementation_request.request_fingerprint: diff}
    )
    implementation_adapter = ImplementationExecutionAdapter(
        adapter_id="adapter.implementation.reference",
        provider=provider,
        requests=(implementation_request,),
    )
    from phase4.authority.grants import VerifiedAuthorityGrant
    execution_result = ExecutionEngine((implementation_adapter,)).execute(
        implementation_request.execution_request(idempotency_key="REQ-CALC-1"),
        VerifiedAuthorityGrant.from_decision(authority),
    )
=======
    provider = DeterministicFakeImplementationProvider({implementation_request.request_fingerprint: diff})
    implementation_adapter = ImplementationExecutionAdapter(adapter_id="adapter.implementation.reference", provider=provider, requests=(implementation_request,))
    grant = VerifiedAuthorityGrant.from_decision(authority)
    execution_result = ExecutionEngine((implementation_adapter,)).execute(implementation_request.execution_request(idempotency_key="REQ-CALC-1"), grant)
>>>>>>> origin/phase4/p4-08-02-safe-patch-apply-v3
    outcome = OutcomeEngine().process(execution_result)

    assert agent.has_capability(IMPLEMENTATION_ACTION)
    assert authority.allowed is True
    assert grant.verified is True
    assert execution_result.status is ExecutionStatus.SUCCEEDED
    assert outcome.status is OutcomeStatus.SUCCEEDED
    assert outcome.execution_id == execution_result.execution_id
    proposal_id = dict(execution_result.output)["proposal_id"]
    proposal = implementation_adapter.get_proposal(proposal_id)
    assert proposal.touched_paths == ("src/calculator.py",)
    assert proposal.changed_lines == 2
    assert proposal.unified_diff == diff
    assert provider.calls == (implementation_request.request_fingerprint,)
    assert not hasattr(proposal, "apply")
