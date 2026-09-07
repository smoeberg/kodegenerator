from __future__ import annotations

import pytest

from phase4.development_governance.contracts import (
    GOVERNANCE_EFFECTIVE_BOUNDARY,
    GRANDFATHERED_WORK_UNITS,
    GovernanceContractError,
    ProblemApproval,
    ProblemBrief,
    ProblemDecision,
    ScopeConformance,
    SolutionApproval,
    SolutionDecision,
    SolutionProposal,
)


def problem(version: int = 1) -> ProblemBrief:
    return ProblemBrief(
        problem_id="gov-problem-1",
        version=version,
        title="Separate development authority",
        observed_problem="One role can otherwise propose and self-ratify semantic change.",
        impact="Semantic change can proceed without independent product authority.",
        evidence_refs=("WQ-104-intake",),
        affected_concepts=("development governance",),
        constraints=("no new scheduler",),
        non_goals=("no governance database",),
        proposed_scope=("development governance v0",),
    )


def approval(p: ProblemBrief) -> ProblemApproval:
    return ProblemApproval(
        problem_id=p.problem_id,
        problem_version=p.version,
        problem_fingerprint=p.fingerprint,
        decided_by="product-owner",
        decision=ProblemDecision.APPROVED_FOR_DESIGN,
        approved_scope=("development governance v0",),
        constraints=("no new scheduler",),
        explicit_non_goals=("no governance database",),
    )


def solution(p: ProblemBrief, a: ProblemApproval) -> SolutionProposal:
    return SolutionProposal(
        solution_id="solution-1",
        version=1,
        problem_id=p.problem_id,
        problem_approval_fingerprint=a.fingerprint,
        proposed_design="Use two Product Owner gates and a separate evidence/review chain.",
        why_this_is_minimal="It adds contracts and routing only.",
        scope_conformance=ScopeConformance.WITHIN_APPROVED_SCOPE,
        approved_scope=a.approved_scope,
        explicit_non_goals=a.explicit_non_goals,
        acceptance_invariants=("no self-ratification",),
    )


def test_effective_boundary_and_grandfathering_are_exact() -> None:
    assert GOVERNANCE_EFFECTIVE_BOUNDARY == "7f91611e2a3f0bf81449551f72a85418f3f27e3d"
    assert GRANDFATHERED_WORK_UNITS == ("WQ-101", "WQ-102", "WQ-103", "WQ-104")


def test_problem_fingerprint_changes_when_semantic_content_changes() -> None:
    first = problem()
    changed = ProblemBrief(
        **{
            **first.__dict__,
            "constraints": ("no new scheduler", "no persistence"),
        }
    )
    assert first.fingerprint != changed.fingerprint


def test_problem_approval_is_bound_to_exact_problem_fingerprint() -> None:
    p = problem()
    a = approval(p)
    assert a.problem_fingerprint == p.fingerprint
    assert len(a.fingerprint) == 64


def test_approved_problem_requires_explicit_scope() -> None:
    p = problem()
    with pytest.raises(GovernanceContractError, match="approved_scope"):
        ProblemApproval(
            problem_id=p.problem_id,
            problem_version=p.version,
            problem_fingerprint=p.fingerprint,
            decided_by="product-owner",
            decision=ProblemDecision.APPROVED_FOR_DESIGN,
        )


def test_within_scope_solution_cannot_hide_scope_delta() -> None:
    p = problem()
    a = approval(p)
    with pytest.raises(GovernanceContractError, match="scope_delta"):
        SolutionProposal(
            solution_id="solution-1",
            version=1,
            problem_id=p.problem_id,
            problem_approval_fingerprint=a.fingerprint,
            proposed_design="design",
            why_this_is_minimal="minimal",
            scope_conformance=ScopeConformance.WITHIN_APPROVED_SCOPE,
            approved_scope=a.approved_scope,
            explicit_non_goals=a.explicit_non_goals,
            scope_delta=("new authority subsystem",),
        )


def test_scope_expansion_requires_explicit_delta() -> None:
    p = problem()
    a = approval(p)
    with pytest.raises(GovernanceContractError, match="scope_delta"):
        SolutionProposal(
            solution_id="solution-1",
            version=1,
            problem_id=p.problem_id,
            problem_approval_fingerprint=a.fingerprint,
            proposed_design="design",
            why_this_is_minimal="minimal",
            scope_conformance=ScopeConformance.SCOPE_EXPANSION_REQUIRED,
            approved_scope=a.approved_scope,
            explicit_non_goals=a.explicit_non_goals,
        )


def test_solution_approval_is_bound_to_exact_solution_and_problem_approval() -> None:
    p = problem()
    a = approval(p)
    s = solution(p, a)
    decision = SolutionApproval(
        solution_id=s.solution_id,
        solution_version=s.version,
        solution_fingerprint=s.fingerprint,
        problem_approval_fingerprint=a.fingerprint,
        decided_by="product-owner",
        decision=SolutionDecision.APPROVED_FOR_IMPLEMENTATION,
    )
    assert decision.solution_fingerprint == s.fingerprint
    assert decision.problem_approval_fingerprint == a.fingerprint


def test_duplicate_contract_items_fail_closed() -> None:
    with pytest.raises(GovernanceContractError, match="duplicates"):
        ProblemBrief(
            problem_id="p",
            version=1,
            title="t",
            observed_problem="o",
            impact="i",
            constraints=("same", "same"),
        )
