from phase4.authority import VerifiedAuthorityGrant
from phase4.execution import ExecutionStatus
from phase4.implementation_agent import ChangeBudget, ImplementationAgentRuntime
from phase4.implementation_agent.models import ImplementationRequest
from phase4.context_packet import ContextItem
from phase4.implementation_agent import PatchCandidate


RESOURCE = "repository:smoeberg/kodegenerator"

VALID_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-VALUE = 1
+VALUE = 2
"""


class StaticProvider:
    provider_id = "fake.p4-08-01"

    def propose_patch(self, request: ImplementationRequest) -> PatchCandidate:
        return PatchCandidate(VALID_DIFF)


def test_implementation_runtime_issues_verified_grant_and_uses_exact_context_binding():
    runtime = ImplementationAgentRuntime(
        provider=StaticProvider(),
        allowed_resources=(RESOURCE,),
    )
    context = (
        ContextItem(
            source="repository",
            key="src/app.py",
            value="VALUE = 1\n",
            provenance="git:abc123:src/app.py",
        ),
    )

    run = runtime.run(
        resource=RESOURCE,
        instruction="Set VALUE to 2.",
        allowed_paths=("src/app.py",),
        context_items=context,
        budget=ChangeBudget(max_files=1, max_changed_lines=2),
        idempotency_key="p4-08-01-command",
    )

    assert run.execution.status is ExecutionStatus.SUCCEEDED
    assert isinstance(run.authority_grant, VerifiedAuthorityGrant)
    assert run.authority_grant.verified is True
    assert run.authority_grant.request_id == run.request.authority_request().request_id
    assert run.authority_grant.agent_identity == run.request.agent_identity
    assert run.authority_grant.action == run.request.authority_request().action
    assert run.authority_grant.resource == run.request.resource
    assert run.authority_grant.context_packet_id == run.context_packet.packet_id
    assert run.request.context_packet_id == run.context_packet.packet_id
