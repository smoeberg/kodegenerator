"""Tests for Specialist Agent Council Deliberation Engine."""
import pytest
from domain.council_agents import AgentPosition, AgentRole, DeliberationAgenda
from domain.decision import DecisionCategory, RiskLevel
from services.deliberation_engine import DeliberationEngine


def test_deliberation_engine_basic_synthesis():
    engine = DeliberationEngine()
    agenda = DeliberationAgenda(
        agenda_id="agenda-101",
        project_id="proj-eira",
        topic="Database Storage Strategy",
        description="Select primary storage for audit and state",
        options=["PostgreSQL", "SQLite", "DynamoDB"],
    )

    positions = [
        AgentPosition(
            agent_id="bot-arch",
            role=AgentRole.ARCHITECT,
            preferred_alternative="PostgreSQL",
            confidence=0.95,
            reasoning="Postgres offers solid ACID compliance and JSONB AST storage.",
        ),
        AgentPosition(
            agent_id="bot-sec",
            role=AgentRole.SECURITY,
            preferred_alternative="PostgreSQL",
            confidence=0.90,
            reasoning="Proven access controls and encryption at rest.",
            identified_risks=["Requires proper connection pool sizing"],
        ),
        AgentPosition(
            agent_id="bot-pm",
            role=AgentRole.PM,
            preferred_alternative="PostgreSQL",
            confidence=0.85,
            reasoning="Aligns with production SLA and team velocity.",
        ),
    ]

    decision = engine.deliberate_and_synthesize(
        agenda,
        positions,
        category=DecisionCategory.ARCHITECTURE,
        risk_level=RiskLevel.HIGH,
    )

    assert decision.decision_id == "dec-agenda-101"
    assert decision.project_id == "proj-eira"
    assert len(decision.alternatives) == 3
    assert len(decision.agent_votes) == 3
    assert decision.provenance_id is not None
    assert len(decision.provenance_id) == 64


def test_deliberation_engine_veto_handling():
    engine = DeliberationEngine()
    agenda = DeliberationAgenda(
        agenda_id="agenda-102",
        project_id="proj-eira",
        topic="Authentication Token Strategy",
        description="Select token format",
        options=["Plain-JWT", "Signed-Opaque-Token"],
    )

    positions = [
        AgentPosition(
            agent_id="bot-sec",
            role=AgentRole.SECURITY,
            preferred_alternative="Plain-JWT",
            confidence=0.1,
            reasoning="Plain unsigned JWT allows tampering.",
            veto=True,
            identified_risks=["Vulnerable to token forgery"],
        ),
        AgentPosition(
            agent_id="bot-arch",
            role=AgentRole.ARCHITECT,
            preferred_alternative="Signed-Opaque-Token",
            confidence=0.95,
            reasoning="Opaque signed tokens with server-side revocation.",
        ),
    ]

    decision = engine.deliberate_and_synthesize(agenda, positions)
    assert len(decision.alternatives) == 2
    plain_jwt_alt = next(a for a in decision.alternatives if a.key == "PLAIN-JWT")
    assert plain_jwt_alt.risk_level == RiskLevel.CRITICAL


def test_deliberation_engine_requires_positions():
    engine = DeliberationEngine()
    agenda = DeliberationAgenda(
        agenda_id="agenda-103",
        project_id="proj-eira",
        topic="Empty test",
        description="Should raise error",
        options=["A", "B"],
    )

    with pytest.raises(ValueError, match="at least one agent position"):
        engine.deliberate_and_synthesize(agenda, [])
