"""Failure classifier categorizing runtime and execution errors."""

from __future__ import annotations

import re
from typing import Optional

from .models import ExecutionFailure, FailureCategory


class FailureClassifier:
    """Classifies execution failures into structured failure categories."""

    ENV_PATTERNS = [
        re.compile(r"connection refused", re.I),
        re.compile(r"out of memory|oomkilled", re.I),
        re.compile(r"no space left on device|disk full", re.I),
        re.compile(r"network unreachable|host is unreachable|etimedout", re.I),
        re.compile(r"database connection failed|psycopg2\.operationalerror", re.I),
        re.compile(r"docker daemon|container killed", re.I),
    ]

    POLICY_PATTERNS = [
        re.compile(r"permission denied", re.I),
        re.compile(r"unauthorized|forbidden|401|403", re.I),
        re.compile(r"policy violation|security policy denied", re.I),
        re.compile(r"sandboxed syscall restricted", re.I),
    ]

    @classmethod
    def classify(
        cls,
        current_failure: ExecutionFailure,
        previous_failure: Optional[ExecutionFailure] = None,
    ) -> FailureCategory:
        """Classify a failure based on current details and prior execution context."""
        msg_and_type = f"{current_failure.error_type} {current_failure.error_message} {current_failure.stack_trace or ''}"

        # 1. Check Policy Denial
        for pat in cls.POLICY_PATTERNS:
            if pat.search(msg_and_type):
                return FailureCategory.POLICY_DENIAL

        # 2. Check Environment Failure
        for pat in cls.ENV_PATTERNS:
            if pat.search(msg_and_type):
                return FailureCategory.ENVIRONMENT_FAILURE

        # 3. Check Regression (previously passing tests now failing, or new test failure regressions)
        if current_failure.newly_failed_tests:
            return FailureCategory.REGRESSION

        # 4. Check Identical Failure (SAME_FAILURE) vs Previous Failure
        if previous_failure is not None:
            if cls._is_same_failure(current_failure, previous_failure):
                return FailureCategory.SAME_FAILURE

        # 5. Fallback classification
        if current_failure.failed_tests or current_failure.error_type:
            # If no previous failure to compare against or tests failed, default to same test failure pattern or unknown
            return FailureCategory.UNKNOWN

        return FailureCategory.UNKNOWN

    @classmethod
    def _is_same_failure(cls, curr: ExecutionFailure, prev: ExecutionFailure) -> bool:
        """Evaluate if two failures represent identical failure symptoms."""
        # Compare error types
        if curr.error_type.strip() == prev.error_type.strip() and curr.error_type.strip():
            # Check if messages or failed test sets match
            if curr.failed_tests and prev.failed_tests:
                if set(curr.failed_tests) == set(prev.failed_tests):
                    return True
            if curr.error_message.strip() == prev.error_message.strip() and curr.error_message.strip():
                return True

        # Check exact failed tests match even if error type differs slightly
        if curr.failed_tests and prev.failed_tests and set(curr.failed_tests) == set(prev.failed_tests):
            return True

        return False
