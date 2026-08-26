"""Unit tests for Phase 4 Adaptation module."""

import pytest

from phase4.adaptation import (
    AdaptationAction,
    AntiTubeTrigger,
    ExecutionFailure,
    FailureCategory,
    FailureClassifier,
    StrategyFingerprinter,
)


def test_strategy_fingerprinter_deterministic_hash():
    """Test that fingerprinter creates consistent SHA-256 summary hash."""
    fp1 = StrategyFingerprinter.create(
        hypothesis_id="hyp-101",
        affected_files=["src/server.py", "src/config.py"],
        change_pattern="add connection timeout retry",
    )

    # Re-order files and whitespace
    fp2 = StrategyFingerprinter.create(
        hypothesis_id="hyp-101",
        affected_files=["src/config.py", "src/server.py"],
        change_pattern="  add connection timeout retry  ",
    )

    assert fp1.summary_hash == fp2.summary_hash
    assert fp1.affected_files == ["src/config.py", "src/server.py"]
    assert fp1.change_pattern == "add connection timeout retry"


def test_failure_classifier_categories():
    """Test classification for environment failures, policy denials, regressions and identical failures."""
    # 1. Environment failure
    env_fail = ExecutionFailure(
        task_id="task-1",
        error_type="OperationalError",
        error_message="psycopg2.OperationalError: Connection refused on port 5432",
    )
    assert FailureClassifier.classify(env_fail) == FailureCategory.ENVIRONMENT_FAILURE

    # 2. Policy denial
    policy_fail = ExecutionFailure(
        task_id="task-1",
        error_type="PermissionError",
        error_message="Permission denied: sandboxed syscall restricted by security policy",
    )
    assert FailureClassifier.classify(policy_fail) == FailureCategory.POLICY_DENIAL

    # 3. Regression
    reg_fail = ExecutionFailure(
        task_id="task-1",
        error_type="AssertionError",
        error_message="Expected 200 got 500",
        failed_tests=["test_login", "test_auth_flow"],
        newly_failed_tests=["test_auth_flow"],
    )
    assert FailureClassifier.classify(reg_fail) == FailureCategory.REGRESSION

    # 4. Same failure comparison
    fail_a = ExecutionFailure(
        task_id="task-1",
        error_type="IndexError",
        error_message="list index out of range",
        failed_tests=["test_indexing"],
    )
    fail_b = ExecutionFailure(
        task_id="task-1",
        error_type="IndexError",
        error_message="list index out of range",
        failed_tests=["test_indexing"],
    )
    assert FailureClassifier.classify(fail_b, previous_failure=fail_a) == FailureCategory.SAME_FAILURE


def test_anti_tube_trigger_pivot_on_second_same_failure():
    """Test that two consecutive identical failures trigger PIVOT_REQUEST and force pivot."""
    trigger = AntiTubeTrigger(same_failure_threshold=2)
    fingerprint = StrategyFingerprinter.create(
        hypothesis_id="hyp-500",
        affected_files=["src/auth.py"],
        change_pattern="bypass oauth token expiry check",
    )

    fail_1 = ExecutionFailure(
        task_id="task-auth",
        error_type="TokenExpiredError",
        error_message="JWT token expired at timestamp 1700000000",
        failed_tests=["test_jwt_validation"],
    )

    # First attempt -> RETRY permitted
    res_1 = trigger.evaluate_failure(fingerprint, fail_1)
    assert res_1.action == AdaptationAction.RETRY
    assert res_1.pivot_required is False
    assert res_1.consecutive_same_failures == 1

    # Second identical failure -> PIVOT_REQUEST triggered
    fail_2 = ExecutionFailure(
        task_id="task-auth",
        error_type="TokenExpiredError",
        error_message="JWT token expired at timestamp 1700000000",
        failed_tests=["test_jwt_validation"],
    )

    res_2 = trigger.evaluate_failure(fingerprint, fail_2)
    assert res_2.action == AdaptationAction.PIVOT_REQUEST
    assert res_2.category == FailureCategory.SAME_FAILURE
    assert res_2.pivot_required is True
    assert res_2.consecutive_same_failures == 2
    assert "Anti-tube triggered" in res_2.reason


def test_anti_tube_trigger_environment_and_policy_actions():
    """Test distinct actions for environment outage and policy denials."""
    trigger = AntiTubeTrigger()
    fingerprint = StrategyFingerprinter.create(
        hypothesis_id="hyp-600",
        affected_files=["infra/db.py"],
        change_pattern="increase connection pool limit",
    )

    env_fail = ExecutionFailure(
        task_id="task-db",
        error_type="DatabaseError",
        error_message="Database connection failed: host is unreachable",
    )
    res_env = trigger.evaluate_failure(fingerprint, env_fail)
    assert res_env.action == AdaptationAction.HALT_ENVIRONMENT
    assert res_env.category == FailureCategory.ENVIRONMENT_FAILURE
    assert res_env.pivot_required is False

    policy_fail = ExecutionFailure(
        task_id="task-db",
        error_type="SecurityError",
        error_message="Unauthorized access to system keyring: 403 Forbidden",
    )
    res_pol = trigger.evaluate_failure(fingerprint, policy_fail)
    assert res_pol.action == AdaptationAction.POLICY_ESCALATION
    assert res_pol.category == FailureCategory.POLICY_DENIAL
    assert res_pol.pivot_required is False


def test_anti_tube_different_strategies_isolated():
    """Test that failure counts are isolated per strategy fingerprint."""
    trigger = AntiTubeTrigger(same_failure_threshold=2)

    fp_a = StrategyFingerprinter.create("hyp-1", ["a.py"], "pattern a")
    fp_b = StrategyFingerprinter.create("hyp-2", ["b.py"], "pattern b")

    fail = ExecutionFailure(task_id="t1", error_type="E1", error_message="Error 1")

    # One failure on fp_a
    res_a1 = trigger.evaluate_failure(fp_a, fail)
    assert res_a1.action == AdaptationAction.RETRY

    # One failure on fp_b
    res_b1 = trigger.evaluate_failure(fp_b, fail)
    assert res_b1.action == AdaptationAction.RETRY

    # Second failure on fp_a triggers pivot for fp_a only
    res_a2 = trigger.evaluate_failure(fp_a, fail)
    assert res_a2.action == AdaptationAction.PIVOT_REQUEST
    assert res_a2.hypothesis_id == "hyp-1"
