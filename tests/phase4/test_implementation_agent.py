"""Contract tests for Phase 4B-1 Governed Implementation Agent."""

from dataclasses import FrozenInstanceError, replace

import pytest

from phase4.authority import (
    AuthorityEngine,
    AuthorityPolicy,
    AuthorityRule,
    Decision,
)
from phase4.context_packet import ContextItem, ContextPacketEngine, ContextRequest
from phase4.execution import ExecutionEngine, ExecutionStatus
from phase4.implementation_agent import (
    IMPLEMENTATION_ACTION,
    ChangeBudget,
    DuplicateImplementationRequestError,
    ImplementationContractError,
    ImplementationExecutionAdapter,
    ImplementationRequest,
    InvalidPatchError,
    PatchProposal,
    PatchProposalNotFoundError,
)
from phase4.implementation_agent.testing import DeterministicFakeImplementationProvider

VALID_DIFF = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-old = 1
+new = 2
"""


def make_request(
    *,
    agent_identity: str = "agent.implementer",
    allowed_paths=("src/app.py",),
    max_files: int = 1,
    max_changed_lines: int = 10,
    instruction: str = "Change the configured value.",
) -> ImplementationRequest:
    context_packet = ContextPacketEngine().build(
        ContextRequest(
            agent_identity=agent_identity,
            purpose=IMPLEMENTATION_ACTION,
        ),
        (
            ContextItem(
                source="repository",
                key="src/app.py",
                value="old = 1\n",
                provenance="git:base:src/app.py",
            ),
        ),
    )
    return ImplementationRequest(
        agent_identity=agent_identity,
        agent_role="executor",
        resource="repository:smoeberg/kodegenerator",
        context_packet=context_packet,
        instruction=instruction,
        allowed_paths=allowed_paths,
        budget=ChangeBudget(
            max_files=max_files,
            max_changed_lines=max_changed_lines,
        ),
    )


def allow_decision(request: ImplementationRequest):
    authority_request = request.authority_request()
    policy = AuthorityPolicy(
        policy_id="policy.implementation",
        version="1",
        rules=(
            AuthorityRule(
                rule_id="allow-exact-implementation-request",
                action=IMPLEMENTATION_ACTION,
                resource_pattern=request.resource,
                effect=Decision.ALLOW,
                agent_identity=request.agent_identity,
                agent_role=request.agent_role,
                required_context=tuple(sorted(request.authority_context().items())),
            ),
        ),
    )
    return AuthorityEngine(policy).evaluate(authority_request)


def execute(
    request: ImplementationRequest,
    unified_diff: str = VALID_DIFF,
):
    provider = DeterministicFakeImplementationProvider(
        {request.request_fingerprint: unified_diff}
    )
    adapter = ImplementationExecutionAdapter(
        adapter_id="adapter.implementation.fake",
        provider=provider,
        requests=(request,),
    )
    result = ExecutionEngine((adapter,)).execute(
        request.execution_request(idempotency_key="implementation-1"),
        allow_decision(request),
    )
    return result, adapter, provider


class TestImplementationRequest:
    def test_request_is_immutable_and_content_addressed(self):
        request = make_request()
        same = make_request()

        assert request.request_fingerprint == same.request_fingerprint
        assert len(request.request_fingerprint) == 64
        with pytest.raises(FrozenInstanceError):
            request.instruction = "tampered"

    def test_allowed_path_order_does_not_change_identity(self):
        first = make_request(
            allowed_paths=("tests/test_app.py", "src/app.py"),
            max_files=2,
        )
        second = make_request(
            allowed_paths=("src/app.py", "tests/test_app.py"),
            max_files=2,
        )

        assert first.allowed_paths == ("src/app.py", "tests/test_app.py")
        assert first.request_fingerprint == second.request_fingerprint

    @pytest.mark.parametrize(
        "path",
        (
            "/etc/passwd",
            "../secrets.txt",
            "src/../secrets.txt",
            "src\\app.py",
            " src/app.py",
        ),
    )
    def test_unsafe_or_noncanonical_paths_fail_closed(self, path):
        with pytest.raises(ImplementationContractError):
            make_request(allowed_paths=(path,))

    def test_duplicate_scope_paths_are_rejected(self):
        with pytest.raises(ImplementationContractError, match="unique"):
            make_request(allowed_paths=("src/app.py", "src/app.py"))

    def test_budget_cannot_exceed_explicit_file_scope(self):
        with pytest.raises(ImplementationContractError, match="allowed path count"):
            make_request(max_files=2)

    @pytest.mark.parametrize("value", (0, -1))
    def test_budget_must_be_positive(self, value):
        with pytest.raises(ValueError):
            ChangeBudget(max_files=1, max_changed_lines=value)

    def test_boolean_is_not_an_integer_budget(self):
        with pytest.raises(TypeError):
            ChangeBudget(max_files=True, max_changed_lines=10)

    def test_context_packet_must_be_bound_to_agent(self):
        request = make_request()
        with pytest.raises(ImplementationContractError, match="agent identity"):
            replace(request, agent_identity="agent.other")

    def test_authority_question_binds_scope_and_budget(self):
        request = make_request()
        authority_request = request.authority_request()

        assert authority_request.agent_identity == request.agent_identity
        assert authority_request.context_packet_id == request.context_packet_id
        assert authority_request.action == IMPLEMENTATION_ACTION
        assert dict(authority_request.context) == request.authority_context()
        assert not hasattr(request, "authorize")


class TestPatchProposal:
    def test_valid_patch_is_content_addressed_and_bounded(self):
        proposal = PatchProposal(
            request=make_request(),
            provider_id="fake.deterministic",
            unified_diff=VALID_DIFF,
        )

        assert proposal.touched_paths == ("src/app.py",)
        assert proposal.changed_lines == 2
        assert len(proposal.diff_sha256) == 64
        assert len(proposal.proposal_id) == 64
        assert not hasattr(proposal, "apply")

    def test_proposal_is_immutable(self):
        proposal = PatchProposal(make_request(), "fake.deterministic", VALID_DIFF)
        with pytest.raises(FrozenInstanceError):
            proposal.unified_diff = "tampered"

    def test_out_of_scope_path_is_rejected(self):
        diff = VALID_DIFF.replace("src/app.py", "src/secret.py")
        with pytest.raises(InvalidPatchError, match="outside the approved scope"):
            PatchProposal(make_request(), "fake.deterministic", diff)

    def test_changed_line_budget_is_enforced(self):
        with pytest.raises(InvalidPatchError, match="changed-line budget"):
            PatchProposal(
                make_request(max_changed_lines=1),
                "fake.deterministic",
                VALID_DIFF,
            )

    def test_file_budget_is_enforced(self):
        second = """diff --git a/tests/test_app.py b/tests/test_app.py
--- a/tests/test_app.py
+++ b/tests/test_app.py
@@ -1 +1 @@
-assert False
+assert True
"""
        request = make_request(
            allowed_paths=("src/app.py", "tests/test_app.py"),
            max_files=1,
        )
        with pytest.raises(InvalidPatchError, match="file budget"):
            PatchProposal(request, "fake.deterministic", VALID_DIFF + second)

    @pytest.mark.parametrize(
        "diff",
        (
            "not a unified diff",
            "diff --git a/src/app.py b/src/other.py\n",
            "diff --git a/src/app.py b/src/app.py\nGIT binary patch\nliteral 0\n",
            """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1 @@
-old = 1
+new = 2
""",
            """diff --git a/../secret.py b/../secret.py
--- a/../secret.py
+++ b/../secret.py
@@ -1 +1 @@
-old
+new
""",
            VALID_DIFF + VALID_DIFF,
        ),
    )
    def test_invalid_patch_shapes_fail_closed(self, diff):
        with pytest.raises(InvalidPatchError):
            PatchProposal(make_request(), "fake.deterministic", diff)


class TestImplementationAdapter:
    def test_authorized_request_produces_only_a_patch_proposal(self):
        request = make_request()
        result, adapter, provider = execute(request)

        assert result.status is ExecutionStatus.SUCCEEDED
        output = dict(result.output)
        proposal = adapter.get_proposal(output["proposal_id"])
        assert proposal.request is request
        assert output["diff_sha256"] == proposal.diff_sha256
        assert output["touched_paths"] == "src/app.py"
        assert provider.calls == (request.request_fingerprint,)
        assert not hasattr(adapter, "apply_patch")
        assert not hasattr(adapter, "run")

    def test_denied_request_never_reaches_provider(self):
        request = make_request()
        provider = DeterministicFakeImplementationProvider(
            {request.request_fingerprint: VALID_DIFF}
        )
        adapter = ImplementationExecutionAdapter(
            adapter_id="adapter.implementation.fake",
            provider=provider,
            requests=(request,),
        )
        authority = replace(allow_decision(request), decision=Decision.DENY)

        result = ExecutionEngine((adapter,)).execute(
            request.execution_request(), authority
        )

        assert result.status is ExecutionStatus.REJECTED
        assert provider.calls == ()

    def test_tampered_parameters_fail_at_adapter_boundary(self):
        request = make_request()
        provider = DeterministicFakeImplementationProvider(
            {request.request_fingerprint: VALID_DIFF}
        )
        adapter = ImplementationExecutionAdapter(
            adapter_id="adapter.implementation.fake",
            provider=provider,
            requests=(request,),
        )
        execution_request = replace(
            request.execution_request(),
            parameters=(
                ("implementation_request_fingerprint", request.request_fingerprint),
                ("unapproved", "value"),
            ),
        )

        result = ExecutionEngine((adapter,)).execute(
            execution_request, allow_decision(request)
        )

        assert result.status is ExecutionStatus.FAILED
        assert "parameters does not match" in result.error
        assert provider.calls == ()

    def test_unregistered_request_fails_without_provider_call(self):
        request = make_request()
        provider = DeterministicFakeImplementationProvider(
            {request.request_fingerprint: VALID_DIFF}
        )
        adapter = ImplementationExecutionAdapter(
            adapter_id="adapter.implementation.fake",
            provider=provider,
        )

        result = ExecutionEngine((adapter,)).execute(
            request.execution_request(), allow_decision(request)
        )

        assert result.status is ExecutionStatus.FAILED
        assert "ImplementationRequestNotFoundError" in result.error
        assert provider.calls == ()

    def test_duplicate_request_registration_is_rejected(self):
        request = make_request()
        provider = DeterministicFakeImplementationProvider(
            {request.request_fingerprint: VALID_DIFF}
        )
        with pytest.raises(DuplicateImplementationRequestError):
            ImplementationExecutionAdapter(
                adapter_id="adapter.implementation.fake",
                provider=provider,
                requests=(request, request),
            )

    def test_ai4_replay_does_not_call_provider_twice(self):
        request = make_request()
        provider = DeterministicFakeImplementationProvider(
            {request.request_fingerprint: VALID_DIFF}
        )
        adapter = ImplementationExecutionAdapter(
            adapter_id="adapter.implementation.fake",
            provider=provider,
            requests=(request,),
        )
        engine = ExecutionEngine((adapter,))
        execution_request = request.execution_request()
        authority = allow_decision(request)

        first = engine.execute(execution_request, authority)
        second = engine.execute(execution_request, authority)

        assert first.status is ExecutionStatus.SUCCEEDED
        assert second.status is ExecutionStatus.REPLAYED
        assert provider.calls == (request.request_fingerprint,)
        assert len(adapter.proposals()) == 1

    def test_unknown_proposal_fails_explicitly(self):
        request = make_request()
        provider = DeterministicFakeImplementationProvider(
            {request.request_fingerprint: VALID_DIFF}
        )
        adapter = ImplementationExecutionAdapter(
            adapter_id="adapter.implementation.fake",
            provider=provider,
            requests=(request,),
        )
        with pytest.raises(PatchProposalNotFoundError):
            adapter.get_proposal("missing")
