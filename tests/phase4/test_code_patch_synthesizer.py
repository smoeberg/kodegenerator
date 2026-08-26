"""Integration tests for the governed code patch synthesizer (Bot 3 delivery).

The synthesizer is fail-closed: it only approves a patch when the authority
grant verifies, the architecture contract is human-approved, the AST policy
passes, and the sandbox verification succeeds.  These tests exercise the full
canonical path through AuthorityEngine -> VerifiedAuthorityGrant ->
CodePatchSynthesizer, plus adversarial bypass attempts.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from domain.task import Task
from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest
from services.code_patch_synthesizer import (
    ArchitectureSpec,
    CodePatchSynthesizer,
    InProcessSandbox,
    SYNTHESIZE_ACTION,
    AuthorityGrantError,
    AstValidationError,
)


ACTION = SYNTHESIZE_ACTION
RESOURCE = "org-a/checkout_module"
AGENT = "patch-bot"
CONTEXT = "context-1"
ORGANIZATION_ID = "org-a"


def make_architecture(*, status: str = "approved", human: str = "controller-1") -> ArchitectureSpec:
    return ArchitectureSpec(
        contract_id="contract-checkout",
        version="1.0.0",
        module_name="checkout_module",
        status=status,
        public_functions=("run",),
        human_approved_by=human,
    )


def make_task() -> Task:
    return Task(id="T1", name="checkout module", description="do the checkout", status="pending")


def make_authority() -> AuthorityEngine:
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


def make_request(**changes) -> AuthorityRequest:
    base = AuthorityRequest(
        request_id="req-1",
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        requested_at="2026-08-26T00:00:00+00:00",
        parameters=(("task_id", "T1"),),
        organization_id=ORGANIZATION_ID,
    )
    return replace(base, **changes)


def make_grant() -> VerifiedAuthorityGrant:
    decision = make_authority().evaluate(make_request())
    return VerifiedAuthorityGrant.from_decision(decision)


def synthesizer() -> CodePatchSynthesizer:
    return CodePatchSynthesizer(sandbox=InProcessSandbox())


def test_grant_is_born_verified():
    grant = make_grant()
    assert grant.verify() is True
    assert grant.action == ACTION


def test_full_pipeline_approves_clean_patch():
    result = synthesizer().synthesize(
        task=make_task(),
        architecture=make_architecture(),
        grant=make_grant(),
        organization_id=ORGANIZATION_ID,
        principal_id="controller-1",
        actor_id=AGENT,
    )
    assert result.approved is True
    assert result.ast_ok is True
    assert result.sandbox_ok is True
    assert result.module_name == "checkout_module"
    assert result.source_code.startswith('"""')
    assert "def run" in result.source_code
    assert result.source_fingerprint.startswith("def run") or len(result.source_fingerprint) == 64


def test_unapproved_architecture_blocks_patch():
    result = synthesizer().synthesize(
        task=make_task(),
        architecture=make_architecture(status="draft", human=""),
        grant=make_grant(),
        organization_id=ORGANIZATION_ID,
        principal_id="controller-1",
        actor_id=AGENT,
    )
    assert result.approved is False
    assert "not approved" in (result.error or "")


def test_forged_grant_is_rejected_fail_closed():
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
        organization_id=ORGANIZATION_ID,
    )
    with pytest.raises(AuthorityGrantError):
        synthesizer().synthesize(
            task=make_task(),
            architecture=make_architecture(),
            grant=forged,
            organization_id=ORGANIZATION_ID,
            principal_id="controller-1",
            actor_id=AGENT,
        )


def test_forbidden_import_in_source_is_rejected_by_ast_policy():
    class EvilRenderer:
        def __call__(self, task, architecture):
            return "import subprocess\n\ndef run():\n    return 0\n"

    result = synthesizer().__class__(
        sandbox=InProcessSandbox(),
        renderer=EvilRenderer(),
    ).synthesize(
        task=make_task(),
        architecture=make_architecture(),
        grant=make_grant(),
        organization_id=ORGANIZATION_ID,
        principal_id="controller-1",
        actor_id=AGENT,
    )
    assert result.approved is False
    assert "forbidden import" in (result.error or "")
    assert result.ast_ok is False


def test_misbound_grant_resource_is_rejected():
    decision = make_authority().evaluate(
        make_request(resource="org-a/other_module")
    )
    grant = VerifiedAuthorityGrant.from_decision(decision)
    with pytest.raises(AuthorityGrantError):
        synthesizer().synthesize(
            task=make_task(),
            architecture=make_architecture(),
            grant=grant,
            organization_id=ORGANIZATION_ID,
            principal_id="controller-1",
            actor_id=AGENT,
        )
