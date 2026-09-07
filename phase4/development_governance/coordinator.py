"""Automatic Governance v0 routing with fail-closed role separation.

The coordinator calls role providers directly.  A Human Owner is not a prompt
router or scheduler; human escalation remains a provider policy concern for
charter-level ambiguity outside this module.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Protocol

from .contracts import (
    ArtifactSubmission,
    AuditDecision,
    EvidenceReport,
    IndependentReview,
    ProblemApproval,
    ProblemBrief,
    ProblemDecision,
    ReviewDecision,
    SEMANTIC_CHANGE_TRIGGERS,
    ScopeConformance,
    SolutionApproval,
    SolutionDecision,
    SolutionProposal,
)


class GovernanceRoutingError(RuntimeError):
    """Fail-closed Governance v0 routing error."""


class GovernanceBlocked(GovernanceRoutingError):
    """A governance gate intentionally blocked further execution."""


class ProductOwnerProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def review_problem(self, problem: ProblemBrief) -> ProblemApproval: ...

    def review_solution(
        self, problem: ProblemBrief, approval: ProblemApproval, solution: SolutionProposal
    ) -> SolutionApproval: ...


class OrchestratorProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def design(self, problem: ProblemBrief, approval: ProblemApproval) -> SolutionProposal: ...

    def expand_problem(
        self,
        problem: ProblemBrief,
        approval: ProblemApproval,
        solution: SolutionProposal,
    ) -> ProblemBrief: ...


class CoderProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def implement(
        self, problem: ProblemBrief, solution: SolutionProposal, approval: SolutionApproval
    ) -> ArtifactSubmission: ...


class CoreEvidenceVerifier(Protocol):
    """Deterministic source-of-truth verification where possible."""

    def verify(
        self, submission: ArtifactSubmission, solution: SolutionProposal
    ) -> EvidenceReport: ...


class AuditorProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def verify(
        self,
        problem: ProblemBrief,
        solution: SolutionProposal,
        submission: ArtifactSubmission,
        core_evidence: EvidenceReport,
    ) -> EvidenceReport: ...


class ReviewerProvider(Protocol):
    @property
    def provider_id(self) -> str: ...

    def review(
        self,
        problem: ProblemBrief,
        solution: SolutionProposal,
        submission: ArtifactSubmission,
        evidence: EvidenceReport,
    ) -> IndependentReview: ...


@dataclass(frozen=True)
class GovernanceMetricsSnapshot:
    gate_round_trip_count: int
    classification_count: int
    uncertainty_escalation_count: int
    uncertainty_escalation_rate: float
    po_response_latency: float
    scope_expansion_count: int
    semantic_find_count: int
    auditor_veto_count: int
    governance_blocked_time: float


class GovernanceMetrics:
    """Small process-local measurement surface.  Metrics never affect routing."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._gate_round_trips = 0
        self._classification_count = 0
        self._uncertainty_escalations = 0
        self._po_latency = 0.0
        self._scope_expansions = 0
        self._semantic_finds = 0
        self._auditor_vetoes = 0
        self._blocked_time = 0.0

    def record_classification(self, *, uncertain: bool) -> None:
        with self._lock:
            self._classification_count += 1
            if uncertain:
                self._uncertainty_escalations += 1

    def record_po_round_trip(self, seconds: float) -> None:
        _duration(seconds)
        with self._lock:
            self._gate_round_trips += 1
            self._po_latency += seconds

    def record_scope_expansion(self) -> None:
        with self._lock:
            self._scope_expansions += 1

    def record_semantic_find(self) -> None:
        with self._lock:
            self._semantic_finds += 1

    def record_auditor_veto(self) -> None:
        with self._lock:
            self._auditor_vetoes += 1

    def record_blocked_time(self, seconds: float) -> None:
        _duration(seconds)
        with self._lock:
            self._blocked_time += seconds

    def snapshot(self) -> GovernanceMetricsSnapshot:
        with self._lock:
            rate = (
                self._uncertainty_escalations / self._classification_count
                if self._classification_count
                else 0.0
            )
            return GovernanceMetricsSnapshot(
                gate_round_trip_count=self._gate_round_trips,
                classification_count=self._classification_count,
                uncertainty_escalation_count=self._uncertainty_escalations,
                uncertainty_escalation_rate=rate,
                po_response_latency=self._po_latency,
                scope_expansion_count=self._scope_expansions,
                semantic_find_count=self._semantic_finds,
                auditor_veto_count=self._auditor_vetoes,
                governance_blocked_time=self._blocked_time,
            )


def _duration(value: float) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("duration must be numeric")
    if value < 0 or not math.isfinite(float(value)):
        raise ValueError("duration must be finite and non-negative")


def classify_change(changed_dimensions: set[str] | frozenset[str], *, uncertain: bool = False) -> str:
    """Return MECHANICAL only inside the approved observable-contract safe harbor.

    ``uncertain`` means uncertainty about whether a semantic contract changes,
    not ordinary technical difficulty.  False negatives are intentionally
    avoided: unknown dimensions fail closed to SEMANTIC.
    """
    if uncertain:
        return "SEMANTIC"
    if not isinstance(changed_dimensions, (set, frozenset)):
        raise TypeError("changed_dimensions must be a set")
    if any(not isinstance(item, str) or not item.strip() for item in changed_dimensions):
        raise ValueError("changed_dimensions must contain canonical text")
    return "SEMANTIC" if changed_dimensions & SEMANTIC_CHANGE_TRIGGERS else "MECHANICAL"


@dataclass(frozen=True)
class GovernanceRunResult:
    problem: ProblemBrief
    problem_approval: ProblemApproval
    solution: SolutionProposal
    solution_approval: SolutionApproval
    submission: ArtifactSubmission
    core_evidence: EvidenceReport
    audit: EvidenceReport
    review: IndependentReview


class GovernanceCoordinator:
    """Route a semantic change through PO → design → PO → coder → audit → review."""

    def __init__(
        self,
        *,
        product_owner: ProductOwnerProvider,
        orchestrator: OrchestratorProvider,
        coder: CoderProvider,
        core_evidence: CoreEvidenceVerifier,
        auditor: AuditorProvider,
        reviewer: ReviewerProvider,
        metrics: GovernanceMetrics | None = None,
        max_scope_rounds: int = 3,
        monotonic=time.monotonic,
    ) -> None:
        if max_scope_rounds < 1:
            raise ValueError("max_scope_rounds must be positive")
        providers = (product_owner, orchestrator, coder, auditor, reviewer)
        identities = [getattr(provider, "provider_id", "") for provider in providers]
        if any(not isinstance(identity, str) or not identity.strip() for identity in identities):
            raise TypeError("all intelligent role providers require provider_id")
        if len(set(identities)) != len(identities):
            raise GovernanceRoutingError("governance intelligent roles must use distinct provider identities")
        self.product_owner = product_owner
        self.orchestrator = orchestrator
        self.coder = coder
        self.core_evidence = core_evidence
        self.auditor = auditor
        self.reviewer = reviewer
        self.metrics = metrics or GovernanceMetrics()
        self.max_scope_rounds = max_scope_rounds
        self.monotonic = monotonic

    def run_semantic(self, problem: ProblemBrief) -> GovernanceRunResult:
        """Run the complete governed flow without Human Owner prompt routing."""
        blocked_started = self.monotonic()
        current = problem
        try:
            for _ in range(self.max_scope_rounds):
                problem_approval = self._approve_problem(current)
                solution = self.orchestrator.design(current, problem_approval)
                self._validate_solution_binding(current, problem_approval, solution)

                if solution.scope_conformance is ScopeConformance.SCOPE_EXPANSION_REQUIRED:
                    self.metrics.record_scope_expansion()
                    current = self.orchestrator.expand_problem(current, problem_approval, solution)
                    if current.problem_id != problem.problem_id or current.version <= problem_approval.problem_version:
                        raise GovernanceRoutingError("scope expansion must create a newer version of the same ProblemBrief")
                    continue

                solution_approval = self._approve_solution(current, problem_approval, solution)
                if solution_approval.decision is SolutionDecision.SCOPE_EXPANSION_REQUIRED:
                    self.metrics.record_scope_expansion()
                    current = self.orchestrator.expand_problem(current, problem_approval, solution)
                    if current.problem_id != problem.problem_id or current.version <= problem_approval.problem_version:
                        raise GovernanceRoutingError("PO scope expansion must create a newer ProblemBrief")
                    continue
                if solution_approval.decision is not SolutionDecision.APPROVED_FOR_IMPLEMENTATION:
                    self.metrics.record_semantic_find()
                    raise GovernanceBlocked(f"solution gate returned {solution_approval.decision.value}")

                submission = self.coder.implement(current, solution, solution_approval)
                core = self.core_evidence.verify(submission, solution)
                if core.decision is not AuditDecision.VERIFIED:
                    self.metrics.record_auditor_veto()
                    raise GovernanceBlocked("deterministic evidence gate vetoed the artifact")

                audit = self.auditor.verify(current, solution, submission, core)
                self._validate_audit(audit)
                if audit.decision is not AuditDecision.VERIFIED:
                    self.metrics.record_auditor_veto()
                    raise GovernanceBlocked("Auditor vetoed the artifact")

                review = self.reviewer.review(current, solution, submission, audit)
                self._validate_review(solution, submission, review)
                return GovernanceRunResult(
                    problem=current,
                    problem_approval=problem_approval,
                    solution=solution,
                    solution_approval=solution_approval,
                    submission=submission,
                    core_evidence=core,
                    audit=audit,
                    review=review,
                )
            raise GovernanceBlocked("scope-expansion loop exceeded max_scope_rounds")
        finally:
            self.metrics.record_blocked_time(max(0.0, self.monotonic() - blocked_started))

    def _approve_problem(self, problem: ProblemBrief) -> ProblemApproval:
        started = self.monotonic()
        approval = self.product_owner.review_problem(problem)
        self.metrics.record_po_round_trip(max(0.0, self.monotonic() - started))
        if (
            approval.problem_id != problem.problem_id
            or approval.problem_version != problem.version
            or approval.problem_fingerprint != problem.fingerprint
        ):
            raise GovernanceRoutingError("Product Owner problem approval is not bound to exact ProblemBrief")
        if approval.decision is not ProblemDecision.APPROVED_FOR_DESIGN:
            self.metrics.record_semantic_find()
            raise GovernanceBlocked(f"problem gate returned {approval.decision.value}")
        return approval

    def _approve_solution(
        self, problem: ProblemBrief, problem_approval: ProblemApproval, solution: SolutionProposal
    ) -> SolutionApproval:
        started = self.monotonic()
        approval = self.product_owner.review_solution(problem, problem_approval, solution)
        self.metrics.record_po_round_trip(max(0.0, self.monotonic() - started))
        if (
            approval.solution_id != solution.solution_id
            or approval.solution_version != solution.version
            or approval.solution_fingerprint != solution.fingerprint
            or approval.problem_approval_fingerprint != problem_approval.fingerprint
        ):
            raise GovernanceRoutingError("Product Owner solution approval is not bound to exact proposal")
        return approval

    @staticmethod
    def _validate_solution_binding(
        problem: ProblemBrief, approval: ProblemApproval, solution: SolutionProposal
    ) -> None:
        if solution.problem_id != problem.problem_id:
            raise GovernanceRoutingError("solution references a different problem")
        if solution.problem_approval_fingerprint != approval.fingerprint:
            raise GovernanceRoutingError("solution is not bound to exact problem approval")
        if solution.approved_scope != approval.approved_scope:
            raise GovernanceRoutingError("solution silently changed approved_scope")
        if solution.explicit_non_goals != approval.explicit_non_goals:
            raise GovernanceRoutingError("solution silently changed explicit_non_goals")

    @staticmethod
    def _validate_audit(report: EvidenceReport) -> None:
        if report.decision is AuditDecision.VERIFIED and (
            not report.proof_construction_verified or not report.solution_conformance_verified
        ):
            raise GovernanceRoutingError(
                "Auditor cannot return VERIFIED without proof-construction and solution-conformance verification"
            )

    def _validate_review(
        self, solution: SolutionProposal, submission: ArtifactSubmission, review: IndependentReview
    ) -> None:
        if review.artifact_version != submission.artifact_version:
            raise GovernanceRoutingError("review references a different artifact")
        if review.solution_fingerprint != solution.fingerprint:
            raise GovernanceRoutingError("review references a different solution contract")
        if review.reviewer_id != self.reviewer.provider_id:
            raise GovernanceRoutingError("reviewer identity is not bound to reviewer provider")
        if review.decision not in (ReviewDecision.APPROVED, ReviewDecision.REJECTED):
            raise GovernanceRoutingError("invalid review decision")


__all__ = [
    "AuditorProvider",
    "CoderProvider",
    "CoreEvidenceVerifier",
    "GovernanceBlocked",
    "GovernanceCoordinator",
    "GovernanceMetrics",
    "GovernanceMetricsSnapshot",
    "GovernanceRoutingError",
    "GovernanceRunResult",
    "OrchestratorProvider",
    "ProductOwnerProvider",
    "ReviewerProvider",
    "classify_change",
]
