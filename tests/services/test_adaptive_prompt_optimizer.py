"""Tests for adaptive prompt optimizer and prompt evaluation."""
from __future__ import annotations

import pytest

from services.adaptive_prompt_optimizer import (
    PromptOptimizer,
    PromptVersionStatus,
)
from services.prompt_evals import (
    EvalOutcomeKind,
    PromptEvaluator,
    two_proportion_z_test,
)


def _feed(
    optimizer: PromptOptimizer,
    *,
    tenant_id: str,
    capability: str,
    version_id: str,
    successes: int,
    failures: int,
    kind: EvalOutcomeKind = EvalOutcomeKind.TEST_FAILURE,
    error_message: str = "AssertionError: expected 1",
) -> None:
    for _ in range(successes):
        optimizer.record_outcome(
            tenant_id=tenant_id,
            capability=capability,
            success=True,
            prompt_version_id=version_id,
        )
    for _ in range(failures):
        optimizer.record_outcome(
            tenant_id=tenant_id,
            capability=capability,
            success=False,
            kind=kind,
            error_message=error_message,
            retry_count=1,
            prompt_version_id=version_id,
        )


def test_baseline_and_outcome_metrics_per_tenant():
    opt = PromptOptimizer(evaluator=PromptEvaluator(min_samples=5, min_improvement=0.01))
    v = opt.ensure_baseline("tenant-a", "api")
    assert v.status is PromptVersionStatus.ACTIVE
    opt.record_outcome(
        tenant_id="tenant-a",
        capability="api",
        success=True,
        prompt_version_id=v.version_id,
    )
    opt.record_outcome(
        tenant_id="tenant-a",
        capability="api",
        success=False,
        kind=EvalOutcomeKind.COMPILE_ERROR,
        error_message="SyntaxError: invalid syntax",
        retry_count=2,
        prompt_version_id=v.version_id,
    )
    snap = opt.metrics("tenant-a", "api")
    assert snap.sample_size == 2
    assert snap.successes == 1
    assert snap.compile_errors == 1
    assert snap.mean_retries == 1.0
    opt.ensure_baseline("tenant-b", "api")
    snap_b = opt.metrics("tenant-b", "api")
    assert snap_b.sample_size == 0


def test_candidate_generation_from_failure_patterns():
    opt = PromptOptimizer()
    active = opt.ensure_baseline("acme", "tests")
    for _ in range(5):
        opt.record_outcome(
            tenant_id="acme",
            capability="tests",
            success=False,
            kind=EvalOutcomeKind.COMPILE_ERROR,
            error_message="SyntaxError: expected ':'",
            prompt_version_id=active.version_id,
        )
        opt.record_outcome(
            tenant_id="acme",
            capability="tests",
            success=False,
            kind=EvalOutcomeKind.TEST_FAILURE,
            error_message="AssertionError: edge case failed",
            prompt_version_id=active.version_id,
        )
    candidate = opt.propose_candidate("acme", "tests")
    assert candidate.status is PromptVersionStatus.CANDIDATE
    assert candidate.parent_version_id == active.version_id
    assert "Hardened rules" in candidate.system_instructions
    assert candidate.few_shot
    assert any(e.source == "failure_mining" for e in candidate.few_shot)
    rendered = candidate.render("Write a unit test for divide()")
    assert "Current task" in rendered
    assert "divide()" in rendered


def test_ab_promotion_requires_statistical_significance():
    evaluator = PromptEvaluator(alpha=0.05, min_samples=20, min_improvement=0.02)
    opt = PromptOptimizer(evaluator=evaluator, drift_min_samples=100)
    control = opt.ensure_baseline("acme", "service")
    candidate = opt.propose_candidate("acme", "service")

    _feed(opt, tenant_id="acme", capability="service", version_id=control.version_id,
          successes=20, failures=20)
    _feed(opt, tenant_id="acme", capability="service", version_id=candidate.version_id,
          successes=32, failures=8)

    promoted, result = opt.evaluate_and_maybe_promote(
        "acme", "service", candidate.version_id
    )
    assert promoted is True
    assert result.significant is True
    assert result.improvement > 0
    assert opt.get_active("acme", "service").version_id == candidate.version_id
    assert control.status is PromptVersionStatus.RETIRED

    weak = opt.propose_candidate("acme", "service")
    _feed(opt, tenant_id="acme", capability="service", version_id=weak.version_id,
          successes=20, failures=20)
    ok, weak_result = opt.evaluate_and_maybe_promote("acme", "service", weak.version_id)
    assert ok is False
    assert weak.status is PromptVersionStatus.CANDIDATE
    assert "significant" in weak_result.reason or "improvement" in weak_result.reason or "sample" in weak_result.reason


def test_rollback_and_drift_auto_revert():
    evaluator = PromptEvaluator(min_samples=5, min_improvement=0.01)
    opt = PromptOptimizer(
        evaluator=evaluator,
        drift_threshold=0.10,
        drift_min_samples=15,
    )
    baseline = opt.ensure_baseline("acme", "domain")
    candidate = opt.propose_candidate("acme", "domain")
    _feed(opt, tenant_id="acme", capability="domain", version_id=baseline.version_id,
          successes=10, failures=10)
    _feed(opt, tenant_id="acme", capability="domain", version_id=candidate.version_id,
          successes=18, failures=2)
    ok, _ = opt.evaluate_and_maybe_promote("acme", "domain", candidate.version_id)
    assert ok is True
    for _ in range(20):
        opt.record_outcome(
            tenant_id="acme",
            capability="domain",
            success=False,
            kind=EvalOutcomeKind.TEST_FAILURE,
            error_message="AssertionError: invariant broken",
            prompt_version_id=candidate.version_id,
        )
    active = opt.get_active("acme", "domain")
    assert active.version_id != candidate.version_id or candidate.status is PromptVersionStatus.ROLLED_BACK
    events = opt.audit_log(tenant_id="acme", capability="domain")
    actions = {e.action for e in events}
    assert "rollback" in actions or "promoted" in actions


def test_manual_rollback_and_audit_trail():
    opt = PromptOptimizer(evaluator=PromptEvaluator(min_samples=5, min_improvement=0.01))
    v1 = opt.ensure_baseline("acme", "docs")
    v2 = opt.propose_candidate("acme", "docs")
    _feed(opt, tenant_id="acme", capability="docs", version_id=v1.version_id,
          successes=8, failures=2)
    _feed(opt, tenant_id="acme", capability="docs", version_id=v2.version_id,
          successes=15, failures=0)
    ok, _ = opt.evaluate_and_maybe_promote("acme", "docs", v2.version_id)
    assert ok is True
    restored = opt.rollback("acme", "docs", to_version_id=v1.version_id, reason="operator_request")
    assert restored.version_id == v1.version_id
    assert opt.get_active("acme", "docs").version_id == v1.version_id
    audit = opt.audit_log(tenant_id="acme")
    assert any(e.action == "rollback" for e in audit)
    assert all(e.tenant_id == "acme" for e in audit)


def test_two_proportion_z_test_edge_cases():
    r = two_proportion_z_test(5, 10, 8, 10, min_samples=20)
    assert r.significant is False
    assert "sample" in r.reason
    r2 = two_proportion_z_test(50, 100, 80, 100, min_samples=20, min_improvement=0.02)
    assert r2.significant is True
    assert r2.improvement == pytest.approx(0.3)
    r3 = two_proportion_z_test(80, 100, 81, 100, min_samples=20, min_improvement=0.05)
    assert r3.significant is False
