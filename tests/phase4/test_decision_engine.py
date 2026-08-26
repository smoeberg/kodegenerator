from __future__ import annotations

import pytest

from domain.decision import (
    AgentVote,
    Decision,
    DecisionAlternative,
    DecisionCategory,
    DecisionStatus,
    HumanDecision,
    RiskLevel,
)
from domain.human_control_policy import HumanControlPolicy
from services.decision_gate_service import DecisionGateError, DecisionGateService


def alternative(key: str = "A") -> DecisionAlternative:
    return DecisionAlternative(
        key=key,
        title=f"Option {key}",
        description="Test alternative",
        pros=["simple"],
        cons=["trade-off"],
        risks=["test risk"],
        risk_level=RiskLevel.MEDIUM,
    )


def decision(
    *,
    category: DecisionCategory = DecisionCategory.TECHNICAL,
    risk_level: RiskLevel = RiskLevel.HIGH,
) -> Decision:
    return Decision(
        project_id="project-1",
        category=category,
        question="Which option should be used?",
        alternatives=[alternative("A"), alternative("B")],
        provenance_id="prov-1",
        risk_level=risk_level,
    )


def test_high_risk_decision_requires_human() -> None:
    service = DecisionGateService()
    result = service.create(decision())

    assert result.status is DecisionStatus.HUMAN_REQUIRED
    assert service.pending(project_id="project-1")[0].decision_id == result.decision_id


def test_architecture_is_human_required_even_when_low_risk() -> None:
    service = DecisionGateService()
    result = service.create(
        decision(category=DecisionCategory.ARCHITECTURE, risk_level=RiskLevel.LOW)
    )

    assert result.status is DecisionStatus.HUMAN_REQUIRED


def test_low_risk_decision_is_autonomous() -> None:
    service = DecisionGateService()
    result = service.create(decision(risk_level=RiskLevel.LOW))

    assert result.status is DecisionStatus.APPROVED
    assert result.human_decision is not None
    assert result.human_decision.selected_alternative == "A"


def test_human_can_resolve_required_decision() -> None:
    service = DecisionGateService()
    created = service.create(decision())

    resolved = service.resolve_human(
        created.decision_id,
        selected_alternative="B",
        rationale="B is safer for the project constraints.",
        decided_by="human:controller",
    )

    assert resolved.status is DecisionStatus.APPROVED
    assert resolved.human_decision is not None
    assert resolved.human_decision.selected_alternative == "B"
    assert resolved.resolved_at is not None
    assert service.pending() == []


def test_invalid_human_choice_is_rejected() -> None:
    service = DecisionGateService()
    created = service.create(decision())

    with pytest.raises(ValueError):
        service.resolve_human(
            created.decision_id,
            selected_alternative="C",
            rationale="invalid",
            decided_by="human:controller",
        )


def test_medium_risk_requires_unanimous_council() -> None:
    service = DecisionGateService()
    created = service.create(decision(risk_level=RiskLevel.MEDIUM))

    votes = [
        AgentVote(
            agent_id="architect",
            selected_alternative="A",
            argument="A has the best architectural fit.",
            confidence=0.9,
            provenance_id="vote-1",
        ),
        AgentVote(
            agent_id="security",
            selected_alternative="A",
            argument="A has lower operational risk.",
            confidence=0.85,
            provenance_id="vote-2",
        ),
    ]

    resolved = service.resolve_by_council(created.decision_id, votes)
    assert resolved.status is DecisionStatus.APPROVED
    assert resolved.human_decision is not None
    assert resolved.human_decision.decided_by == "system:agent-council"


def test_non_unanimous_council_cannot_resolve() -> None:
    service = DecisionGateService()
    created = service.create(decision(risk_level=RiskLevel.MEDIUM))
    votes = [
        AgentVote(
            agent_id="architect",
            selected_alternative="A",
            argument="A",
            confidence=0.8,
            provenance_id="vote-1",
        ),
        AgentVote(
            agent_id="security",
            selected_alternative="B",
            argument="B",
            confidence=0.8,
            provenance_id="vote-2",
        ),
    ]

    with pytest.raises(DecisionGateError, match="not unanimous"):
        service.resolve_by_council(created.decision_id, votes)


def test_policy_category_override() -> None:
    policy = HumanControlPolicy()
    assert policy.requires_human(
        risk_level=RiskLevel.LOW,
        category=DecisionCategory.RELEASE,
    )
    assert not policy.requires_human(
        risk_level=RiskLevel.LOW,
        category=DecisionCategory.TECHNICAL,
    )


def test_decision_requires_at_least_two_alternatives() -> None:
    with pytest.raises(ValueError):
        Decision(
            project_id="project-1",
            category=DecisionCategory.TECHNICAL,
            question="One option?",
            alternatives=[alternative("A")],
            provenance_id="prov-1",
        )
