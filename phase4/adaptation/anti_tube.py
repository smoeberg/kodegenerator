"""Anti-tube trigger preventing repetitive unviable strategy loops."""

from __future__ import annotations

from typing import Dict, List, Optional

from .classifier import FailureClassifier
from .models import (
    AdaptationAction,
    AdaptationResult,
    ExecutionFailure,
    FailureCategory,
    StrategyFingerprint,
)


class AntiTubeTrigger:
    """Monitors failures against strategy fingerprints and triggers PIVOT_REQUEST when loop detected."""

    def __init__(
        self,
        same_failure_threshold: int = 2,
        failure_classifier: Optional[FailureClassifier] = None,
    ) -> None:
        self.same_failure_threshold = same_failure_threshold
        self.classifier = failure_classifier or FailureClassifier()
        # Mapping: fingerprint_hash -> list of ExecutionFailure
        self._failure_history: Dict[str, List[ExecutionFailure]] = {}
        # Mapping: fingerprint_hash -> count of consecutive SAME_FAILURE
        self._consecutive_same_failures: Dict[str, int] = {}

    def evaluate_failure(
        self,
        fingerprint: StrategyFingerprint,
        current_failure: ExecutionFailure,
    ) -> AdaptationResult:
        """Evaluate failure against the strategy history and determine adaptation action."""
        f_hash = fingerprint.summary_hash
        history = self._failure_history.setdefault(f_hash, [])

        previous_failure = history[-1] if history else None
        category = self.classifier.classify(current_failure, previous_failure)

        history.append(current_failure)

        if category == FailureCategory.SAME_FAILURE:
            # Increment consecutive same failures
            count = self._consecutive_same_failures.get(f_hash, 1) + 1
            self._consecutive_same_failures[f_hash] = count
        else:
            count = 1
            self._consecutive_same_failures[f_hash] = count

        # Check conditions
        if category == FailureCategory.ENVIRONMENT_FAILURE:
            return AdaptationResult(
                action=AdaptationAction.HALT_ENVIRONMENT,
                category=category,
                fingerprint_hash=f_hash,
                hypothesis_id=fingerprint.hypothesis_id,
                consecutive_same_failures=count,
                reason="Infrastructure/environment error encountered. Halt for remediation.",
                pivot_required=False,
            )

        if category == FailureCategory.POLICY_DENIAL:
            return AdaptationResult(
                action=AdaptationAction.POLICY_ESCALATION,
                category=category,
                fingerprint_hash=f_hash,
                hypothesis_id=fingerprint.hypothesis_id,
                consecutive_same_failures=count,
                reason="Security policy denial encountered. Escalation required.",
                pivot_required=False,
            )

        # If SAME_FAILURE hits the threshold (e.g., 2 times on the same strategy fingerprint) -> PIVOT_REQUEST
        if count >= self.same_failure_threshold:
            return AdaptationResult(
                action=AdaptationAction.PIVOT_REQUEST,
                category=category,
                fingerprint_hash=f_hash,
                hypothesis_id=fingerprint.hypothesis_id,
                consecutive_same_failures=count,
                reason=f"Repeated identical failure ({count}x) on strategy '{fingerprint.change_pattern}'. Anti-tube triggered; forcing Council hypothesis pivot.",
                pivot_required=True,
            )

        return AdaptationResult(
            action=AdaptationAction.RETRY,
            category=category,
            fingerprint_hash=f_hash,
            hypothesis_id=fingerprint.hypothesis_id,
            consecutive_same_failures=count,
            reason="Standard retry permitted under current strategy.",
            pivot_required=False,
        )

    def get_failure_count_for_fingerprint(self, fingerprint_hash: str) -> int:
        """Return count of recorded failures for a fingerprint."""
        return len(self._failure_history.get(fingerprint_hash, []))

    def reset_for_fingerprint(self, fingerprint_hash: str) -> None:
        """Reset failure counts if strategy changes."""
        self._consecutive_same_failures.pop(fingerprint_hash, None)
        self._failure_history.pop(fingerprint_hash, None)
