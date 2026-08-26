"""Prompt evaluation primitives: outcome metrics, A/B tests and significance.

Used by :class:`services.adaptive_prompt_optimizer.PromptOptimizer` to decide
whether a candidate prompt template should be promoted over the active version.
All evaluations are tenant-scoped for multi-tenant safety.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvalOutcomeKind(str, Enum):
    """Coarse classification of a single worker-run outcome."""

    SUCCESS = "success"
    COMPILE_ERROR = "compile_error"
    TEST_FAILURE = "test_failure"
    TIMEOUT = "timeout"
    POLICY_REJECT = "policy_reject"
    OTHER_FAILURE = "other_failure"


@dataclass(frozen=True)
class RunOutcome:
    """One worker execution observation for a prompt version."""

    tenant_id: str
    capability: str
    prompt_version_id: str
    success: bool
    kind: EvalOutcomeKind = EvalOutcomeKind.SUCCESS
    retry_count: int = 0
    error_message: str = ""
    latency_ms: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)
    recorded_at: datetime = field(default_factory=_utcnow)

    def __post_init__(self) -> None:
        if self.retry_count < 0:
            raise ValueError("retry_count must be non-negative")
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.capability:
            raise ValueError("capability is required")


@dataclass(frozen=True)
class MetricSnapshot:
    """Aggregated success / failure metrics for a prompt version."""

    tenant_id: str
    capability: str
    prompt_version_id: str
    sample_size: int
    successes: int
    compile_errors: int
    test_failures: int
    other_failures: int
    total_retries: int
    mean_latency_ms: float

    @property
    def success_rate(self) -> float:
        if self.sample_size <= 0:
            return 0.0
        return self.successes / self.sample_size

    @property
    def mean_retries(self) -> float:
        if self.sample_size <= 0:
            return 0.0
        return self.total_retries / self.sample_size

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "capability": self.capability,
            "prompt_version_id": self.prompt_version_id,
            "sample_size": self.sample_size,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 6),
            "compile_errors": self.compile_errors,
            "test_failures": self.test_failures,
            "other_failures": self.other_failures,
            "mean_retries": round(self.mean_retries, 4),
            "mean_latency_ms": round(self.mean_latency_ms, 2),
        }


@dataclass(frozen=True)
class SignificanceResult:
    """Two-proportion significance test outcome."""

    control_rate: float
    candidate_rate: float
    control_n: int
    candidate_n: int
    z_score: float
    p_value: float
    significant: bool
    improvement: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_rate": round(self.control_rate, 6),
            "candidate_rate": round(self.candidate_rate, 6),
            "control_n": self.control_n,
            "candidate_n": self.candidate_n,
            "z_score": round(self.z_score, 4),
            "p_value": round(self.p_value, 6),
            "significant": self.significant,
            "improvement": round(self.improvement, 6),
            "reason": self.reason,
        }


def aggregate_outcomes(
    outcomes: Sequence[RunOutcome],
    *,
    tenant_id: str,
    capability: str,
    prompt_version_id: str,
) -> MetricSnapshot:
    """Aggregate *outcomes* filtered to the given tenant / capability / version."""
    filtered = [
        o
        for o in outcomes
        if o.tenant_id == tenant_id
        and o.capability == capability
        and o.prompt_version_id == prompt_version_id
    ]
    successes = sum(1 for o in filtered if o.success)
    compile_errors = sum(1 for o in filtered if o.kind is EvalOutcomeKind.COMPILE_ERROR)
    test_failures = sum(1 for o in filtered if o.kind is EvalOutcomeKind.TEST_FAILURE)
    other_failures = sum(
        1
        for o in filtered
        if not o.success
        and o.kind
        not in {EvalOutcomeKind.COMPILE_ERROR, EvalOutcomeKind.TEST_FAILURE}
    )
    total_retries = sum(o.retry_count for o in filtered)
    latencies = [o.latency_ms for o in filtered]
    mean_latency = statistics.fmean(latencies) if latencies else 0.0
    return MetricSnapshot(
        tenant_id=tenant_id,
        capability=capability,
        prompt_version_id=prompt_version_id,
        sample_size=len(filtered),
        successes=successes,
        compile_errors=compile_errors,
        test_failures=test_failures,
        other_failures=other_failures,
        total_retries=total_retries,
        mean_latency_ms=mean_latency,
    )


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def two_proportion_z_test(
    control_successes: int,
    control_n: int,
    candidate_successes: int,
    candidate_n: int,
    *,
    alpha: float = 0.05,
    min_samples: int = 20,
    min_improvement: float = 0.02,
) -> SignificanceResult:
    """One-sided two-proportion z-test (candidate > control).

    Returns non-significant when samples are too small, improvement is below
    *min_improvement*, or the pooled-variance z-test fails the alpha threshold.
    """
    if control_n < min_samples or candidate_n < min_samples:
        return SignificanceResult(
            control_rate=(control_successes / control_n) if control_n else 0.0,
            candidate_rate=(candidate_successes / candidate_n) if candidate_n else 0.0,
            control_n=control_n,
            candidate_n=candidate_n,
            z_score=0.0,
            p_value=1.0,
            significant=False,
            improvement=0.0,
            reason=f"insufficient_samples (need>={min_samples})",
        )

    p1 = control_successes / control_n
    p2 = candidate_successes / candidate_n
    improvement = p2 - p1
    if improvement < min_improvement:
        return SignificanceResult(
            control_rate=p1,
            candidate_rate=p2,
            control_n=control_n,
            candidate_n=candidate_n,
            z_score=0.0,
            p_value=1.0,
            significant=False,
            improvement=improvement,
            reason=f"improvement_below_threshold ({improvement:.4f}<{min_improvement})",
        )

    pooled = (control_successes + candidate_successes) / (control_n + candidate_n)
    se = math.sqrt(max(pooled * (1.0 - pooled) * (1.0 / control_n + 1.0 / candidate_n), 1e-12))
    z = (p2 - p1) / se
    p_value = 1.0 - _normal_cdf(z)
    significant = p_value < alpha and improvement >= min_improvement
    reason = "significant_improvement" if significant else "not_significant"
    return SignificanceResult(
        control_rate=p1,
        candidate_rate=p2,
        control_n=control_n,
        candidate_n=candidate_n,
        z_score=z,
        p_value=p_value,
        significant=significant,
        improvement=improvement,
        reason=reason,
    )


@dataclass
class PromptEvaluator:
    """A/B evaluation harness for prompt variants.

    Parameters
    ----------
    alpha:
        Significance level for promotion decisions.
    min_samples:
        Minimum observations per arm before promotion is considered.
    min_improvement:
        Minimum absolute success-rate lift required.
    """

    alpha: float = 0.05
    min_samples: int = 20
    min_improvement: float = 0.02
    _outcomes: list[RunOutcome] = field(default_factory=list, repr=False)

    def record(self, outcome: RunOutcome) -> None:
        """Append a single run outcome to the evaluation buffer."""
        self._outcomes.append(outcome)

    def record_many(self, outcomes: Iterable[RunOutcome]) -> None:
        for outcome in outcomes:
            self.record(outcome)

    @property
    def outcomes(self) -> tuple[RunOutcome, ...]:
        return tuple(self._outcomes)

    def metrics(
        self,
        *,
        tenant_id: str,
        capability: str,
        prompt_version_id: str,
    ) -> MetricSnapshot:
        return aggregate_outcomes(
            self._outcomes,
            tenant_id=tenant_id,
            capability=capability,
            prompt_version_id=prompt_version_id,
        )

    def compare(
        self,
        *,
        tenant_id: str,
        capability: str,
        control_version_id: str,
        candidate_version_id: str,
    ) -> SignificanceResult:
        """Compare candidate vs control using a one-sided two-proportion z-test."""
        control = self.metrics(
            tenant_id=tenant_id,
            capability=capability,
            prompt_version_id=control_version_id,
        )
        candidate = self.metrics(
            tenant_id=tenant_id,
            capability=capability,
            prompt_version_id=candidate_version_id,
        )
        return two_proportion_z_test(
            control.successes,
            control.sample_size,
            candidate.successes,
            candidate.sample_size,
            alpha=self.alpha,
            min_samples=self.min_samples,
            min_improvement=self.min_improvement,
        )

    def should_promote(
        self,
        *,
        tenant_id: str,
        capability: str,
        control_version_id: str,
        candidate_version_id: str,
    ) -> tuple[bool, SignificanceResult]:
        """Return whether the candidate may be promoted and the supporting stats."""
        result = self.compare(
            tenant_id=tenant_id,
            capability=capability,
            control_version_id=control_version_id,
            candidate_version_id=candidate_version_id,
        )
        return result.significant, result
