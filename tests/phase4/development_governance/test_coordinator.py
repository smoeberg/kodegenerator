from __future__ import annotations

import pytest

from phase4.development_governance.contracts import (
    ArtifactSubmission,
    AuditDecision,
    EvidenceReport,
    IndependentReview,
    ProblemApproval,
    ProblemBrief,
    ProblemDecision,
    ReviewDecision,
    ScopeConformance,
    SolutionApproval,
    SolutionDecision,
    SolutionProposal,
)
from phase4.development_governance.coordinator import (
    GovernanceBlocked,
    GovernanceCoordinator,
    GovernanceMetrics,
    GovernanceRoutingError,
    classify_change,
)


def make_problem(version: int = 1, scope: tuple[str, ...] = ("review provenance",)) -> ProblemBrief:
    return ProblemBrief(
        problem_id="WQ-106-governance",
        version=version,
        title="Govern review semantics",
        observed_problem="Review/rework needs an approved semantic contract.",
        impact="Coder could otherwise choose persistence semantics unilaterally.",
        evidence_refs=("WQ-106",),
        affected_concepts=("review", "rework"),
        constraints=("preserve WorkUnit ID",),
        non_goals=("no scheduler",),
        proposed_scope=scope,
    )


class ProductOwner:
    provider_id = "po"

    def __init__(self, calls: list[str], *, problem_decision=ProblemDecision.APPROVED_FOR_DESIGN, solution_decision=SolutionDecision.APPROVED_FOR_IMPLEMENTATION):
        self.calls = calls
        self.problem_decision = problem_decision
        self.solution_decision = solution_decision

    def review_problem(self, problem: ProblemBrief) -> ProblemApproval:
        self.calls.append(f"po.problem.v{problem.version}")
        return ProblemApproval(
            problem_id=problem.problem_id,
            problem_version=problem.version,
            problem_fingerprint=problem.fingerprint,
            decided_by=self.provider_id,
            decision=self.problem_decision,
            approved_scope=problem.proposed_scope if self.problem_decision is ProblemDecision.APPROVED_FOR_DESIGN else (),
            constraints=problem.constraints,
            explicit_non_goals=problem.non_goals,
        )

    def review_solution(self, problem, approval, solution) -> SolutionApproval:
        self.calls.append(f"po.solution.v{solution.version}")
        return SolutionApproval(
            solution_id=solution.solution_id,
            solution_version=solution.version,
            solution_fingerprint=solution.fingerprint,
            problem_approval_fingerprint=approval.fingerprint,
            decided_by=self.provider_id,
            decision=self.solution_decision,
        )


class Orchestrator:
    provider_id = "orchestrator"

    def __init__(self, calls: list[str], *, expand_once: bool = False, silent_scope_drift: bool = False):
        self.calls = calls
        self.expand_once = expand_once
        self.silent_scope_drift = silent_scope_drift

    def design(self, problem: ProblemBrief, approval: ProblemApproval) -> SolutionProposal:
        self.calls.append(f"orchestrator.design.v{problem.version}")
        expansion = self.expand_once and problem.version == 1
        approved_scope = approval.approved_scope
        if self.silent_scope_drift:
            approved_scope = (*approved_scope, "hidden new scope")
        return SolutionProposal(
            solution_id="review-solution",
            version=problem.version,
            problem_id=problem.problem_id,
            problem_approval_fingerprint=approval.fingerprint,
            proposed_design="Minimal review provenance contract.",
            why_this_is_minimal="No scheduler or authority engine.",
            scope_conformance=(
                ScopeConformance.SCOPE_EXPANSION_REQUIRED
                if expansion
                else ScopeConformance.WITHIN_APPROVED_SCOPE
            ),
            approved_scope=approved_scope,
            explicit_non_goals=approval.explicit_non_goals,
            scope_delta=("review evidence persistence",) if expansion else (),
            affected_work_units=("WQ-106",),
        )

    def expand_problem(self, problem, approval, solution) -> ProblemBrief:
        self.calls.append(f"orchestrator.expand.v{problem.version}")
        assert solution.scope_delta
        return make_problem(
            version=problem.version + 1,
            scope=(*approval.approved_scope, *solution.scope_delta),
        )


class Coder:
    provider_id = "coder"

    def __init__(self, calls: list[str]):
        self.calls = calls

    def implement(self, problem, solution, approval) -> ArtifactSubmission:
        self.calls.append("coder")
        return ArtifactSubmission(
            artifact_version="a" * 40,
            base_version="b" * 40,
            changed_files=("phase4/development_governance/example.py",),
            test_claims=("governance-tests=pass",),
        )


class CoreEvidence:
    def __init__(self, calls: list[str], *, veto: bool = False):
        self.calls = calls
        self.veto = veto

    def verify(self, submission, solution) -> EvidenceReport:
        self.calls.append("core-evidence")
        if self.veto:
            return EvidenceReport(
                decision=AuditDecision.VETO,
                facts_verified=("artifact-exists",),
                mismatches=("changed_files mismatch",),
            )
        return EvidenceReport(
            decision=AuditDecision.VERIFIED,
            facts_verified=("artifact-exists", "base-is-ancestor", "changed-files-exact"),
        )


class Auditor:
    provider_id = "auditor"

    def __init__(self, calls: list[str], *, veto: bool = False, incomplete: bool = False):
        self.calls = calls
        self.veto = veto
        self.incomplete = incomplete

    def verify(self, problem, solution, submission, core_evidence) -> EvidenceReport:
        self.calls.append("auditor")
        if self.veto:
            return EvidenceReport(
                decision=AuditDecision.VETO,
                facts_verified=core_evidence.facts_verified,
                mismatches=("test is sequential, not concurrent",),
            )
        return EvidenceReport(
            decision=AuditDecision.VERIFIED,
            facts_verified=(*core_evidence.facts_verified, "proof-construction", "solution-conformance"),
            proof_construction_verified=not self.incomplete,
            solution_conformance_verified=not self.incomplete,
        )


class Reviewer:
    provider_id = "reviewer"

    def __init__(self, calls: list[str], *, decision=ReviewDecision.APPROVED):
        self.calls = calls
        self.decision = decision

    def review(self, problem, solution, submission, evidence) -> IndependentReview:
        self.calls.append("reviewer")
        return IndependentReview(
            artifact_version=submission.artifact_version,
            solution_fingerprint=solution.fingerprint,
            reviewer_id=self.provider_id,
            decision=self.decision,
            findings=() if self.decision is ReviewDecision.APPROVED else ("acceptance mismatch",),
        )


def coordinator(calls: list[str], **overrides) -> GovernanceCoordinator:
    return GovernanceCoordinator(
        product_owner=overrides.get("product_owner", ProductOwner(calls)),
        orchestrator=overrides.get("orchestrator", Orchestrator(calls)),
        coder=overrides.get("coder", Coder(calls)),
        core_evidence=overrides.get("core_evidence", CoreEvidence(calls)),
        auditor=overrides.get("auditor", Auditor(calls)),
        reviewer=overrides.get("reviewer", Reviewer(calls)),
        metrics=overrides.get("metrics"),
    )


def test_complete_flow_routes_roles_without_human_prompt_routing() -> None:
    calls: list[str] = []
    result = coordinator(calls).run_semantic(make_problem())
    assert calls == [
        "po.problem.v1",
        "orchestrator.design.v1",
        "po.solution.v1",
        "coder",
        "core-evidence",
        "auditor",
        "reviewer",
    ]
    assert result.review.decision is ReviewDecision.APPROVED


def test_problem_rejection_blocks_design_and_coder() -> None:
    calls: list[str] = []
    po = ProductOwner(calls, problem_decision=ProblemDecision.REJECTED)
    with pytest.raises(GovernanceBlocked, match="REJECTED"):
        coordinator(calls, product_owner=po).run_semantic(make_problem())
    assert calls == ["po.problem.v1"]


def test_solution_rejection_blocks_coder() -> None:
    calls: list[str] = []
    po = ProductOwner(calls, solution_decision=SolutionDecision.REJECTED_WITH_RATIONALE)
    with pytest.raises(GovernanceBlocked, match="REJECTED_WITH_RATIONALE"):
        coordinator(calls, product_owner=po).run_semantic(make_problem())
    assert "coder" not in calls


def test_scope_expansion_returns_to_problem_gate_before_coding() -> None:
    calls: list[str] = []
    orch = Orchestrator(calls, expand_once=True)
    result = coordinator(calls, orchestrator=orch).run_semantic(make_problem())
    assert calls[:4] == [
        "po.problem.v1",
        "orchestrator.design.v1",
        "orchestrator.expand.v1",
        "po.problem.v2",
    ]
    assert calls.count("coder") == 1
    assert result.problem.version == 2


def test_silent_scope_drift_fails_before_solution_po_or_coder() -> None:
    calls: list[str] = []
    orch = Orchestrator(calls, silent_scope_drift=True)
    with pytest.raises(GovernanceRoutingError, match="approved_scope"):
        coordinator(calls, orchestrator=orch).run_semantic(make_problem())
    assert calls == ["po.problem.v1", "orchestrator.design.v1"]


def test_false_coder_claim_is_vetoed_before_semantic_auditor_and_reviewer() -> None:
    calls: list[str] = []
    core = CoreEvidence(calls, veto=True)
    with pytest.raises(GovernanceBlocked, match="deterministic evidence"):
        coordinator(calls, core_evidence=core).run_semantic(make_problem())
    assert "coder" in calls and "core-evidence" in calls
    assert "auditor" not in calls and "reviewer" not in calls


def test_semantic_auditor_veto_blocks_reviewer() -> None:
    calls: list[str] = []
    auditor = Auditor(calls, veto=True)
    with pytest.raises(GovernanceBlocked, match="Auditor vetoed"):
        coordinator(calls, auditor=auditor).run_semantic(make_problem())
    assert "auditor" in calls
    assert "reviewer" not in calls


def test_auditor_cannot_claim_verified_without_proof_and_conformance() -> None:
    calls: list[str] = []
    auditor = Auditor(calls, incomplete=True)
    with pytest.raises(GovernanceRoutingError, match="proof-construction"):
        coordinator(calls, auditor=auditor).run_semantic(make_problem())


def test_intelligent_roles_require_distinct_provider_identities() -> None:
    calls: list[str] = []
    reviewer = Reviewer(calls)
    reviewer.provider_id = "coder"
    with pytest.raises(GovernanceRoutingError, match="distinct provider"):
        coordinator(calls, reviewer=reviewer)


def test_mechanical_safe_harbor_and_uncertain_fail_closed() -> None:
    assert classify_change({"helper_choice"}) == "MECHANICAL"
    assert classify_change({"concurrency_guarantee"}) == "SEMANTIC"
    assert classify_change(set(), uncertain=True) == "SEMANTIC"


def test_metrics_measure_governance_without_driving_routing() -> None:
    calls: list[str] = []
    metrics = GovernanceMetrics()
    metrics.record_classification(uncertain=False)
    metrics.record_classification(uncertain=True)
    coordinator(calls, metrics=metrics).run_semantic(make_problem())
    snapshot = metrics.snapshot()
    assert snapshot.gate_round_trip_count == 2
    assert snapshot.classification_count == 2
    assert snapshot.uncertainty_escalation_count == 1
    assert snapshot.uncertainty_escalation_rate == 0.5
    assert snapshot.scope_expansion_count == 0
    assert snapshot.auditor_veto_count == 0
