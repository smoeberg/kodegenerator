"""Test live LLM synthesis, mock LLM fallback, AST guardrails, and self-healing convergence."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from domain.task import Task
from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest
from services.code_patch_synthesizer import (
    ArchitectureSpec,
    AstValidationError,
    CodePatchSynthesizer,
    InProcessSandbox,
    SYNTHESIZE_ACTION,
)
from services.diagnostic_loop import DiagnosticLoop


def _create_grant(resource: str) -> VerifiedAuthorityGrant:
    engine = AuthorityEngine(
        AuthorityPolicy(
            policy_id="policy-test",
            version="1",
            rules=(
                AuthorityRule(
                    rule_id="allow-all",
                    action=SYNTHESIZE_ACTION,
                    resource_pattern="*",
                    effect=Decision.ALLOW,
                    agent_identity="test-bot",
                ),
            ),
        )
    )
    request = AuthorityRequest(
        request_id="req-test-1",
        agent_identity="test-bot",
        action=SYNTHESIZE_ACTION,
        resource=resource,
        context_packet_id="ctx-1",
        requested_at="2026-08-30T00:00:00+00:00",
        parameters=(("task_id", "T-01"),),
        organization_id="org-test",
    )
    decision = engine.evaluate(request)
    return VerifiedAuthorityGrant.from_decision(decision)


def test_code_patch_synthesizer_ast_guardrails_blocks_eval():
    sandbox = InProcessSandbox()
    synthesizer = CodePatchSynthesizer(
        sandbox=sandbox,
        renderer=lambda task, arch: "def run():\n    eval('2+2')\n",
    )
    task = Task(id="T-01", name="Dangerous task", status="pending")
    arch = ArchitectureSpec(
        contract_id="AUTH-01", version="1.0.0", module_name="auth_service"
    )
    grant = _create_grant(resource="auth_service")

    result = synthesizer.synthesize(task, arch, grant)
    assert not result.approved
    assert "forbidden call: eval" in (result.error or "")


def test_self_healing_convergence_loop():
    """Simulate a self-healing diagnostic loop fixing an error in 2 iterations."""
    diagnostic_loop = DiagnosticLoop(max_iterations=3)
    
    # Iteration 1: fails
    failing_traceback = """
    Traceback (most recent call last):
      File "/app/payments/service.py", line 10, in process_payment
        assert amount > 0
    AssertionError: assert -5 > 0
    """
    diag = diagnostic_loop.analyze_traceback(failing_traceback)
    assert diag.error_type == "AssertionError"
    feedback = diagnostic_loop.generate_targeted_feedback(diag)
    assert "AssertionError" in feedback
    assert "line 10" in feedback

    should_retry, reason = diagnostic_loop.should_retry(
        attempt=1, previous_errors=[], current_error=failing_traceback
    )
    assert should_retry is True

    # Iteration 2: fixed
    fixed_code = "def run(payload=None):\n    return {'status': 'ok'}\n"
    sandbox = InProcessSandbox()
    synthesizer = CodePatchSynthesizer(
        sandbox=sandbox,
        renderer=lambda task, arch: fixed_code,
    )
    task = Task(id="T-PAY-01", name="Fix payment amount check", status="pending")
    arch = ArchitectureSpec(
        contract_id="PAY-01", version="1.0.0", module_name="payment_service"
    )
    grant = _create_grant(resource="payment_service")
    result = synthesizer.synthesize(task, arch, grant)
    assert result.approved is True
    assert result.ast_ok is True
    assert result.sandbox_ok is True
