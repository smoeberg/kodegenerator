"""Contract tests: frozen assignment plans drive orchestrator deliberation."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.council import CouncilOrchestrator
from phase4.council import CouncilSessionBinding
from phase4.council.configuration import ProtocolFunction
from phase4.council.orchestrator import CouncilStartError
from phase4.council.roles import (
    CouncilAgenda,
    CouncilOrchestrationOutcome,
    CouncilRole,
    CouncilTurnDecision,
    CouncilTurnKind,
)
from phase4.council.routing import AssignmentRoute, CouncilAssignmentPlan
from phase4.council.testing import DeterministicFakeCouncilProvider
from phase4.epistemics import Evidence, EvidenceType, Hypothesis, HypothesisStatus


def _capability(name: str) -> Capability:
    return Capability.create(name, AgentVersion(1, 0, 0))


def _registry() -> AgentRegistry:
    registry = AgentRegistry()
    declarations = [
        ("proposer", "council.propose"),
        ("architect", "council.review.architecture"),
        ("security", "council.review.security"),
        ("qa", "council.review.qa"),
    ]
    for instance_id, capability in declarations:
        registry.register(
            agent_type=f"council-{instance_id}",
            instance_id=instance_id,
            version=AgentVersion(1, 0, 0),
            role=AgentRole.AUDITOR,
            capabilities=(_capability(capability),),
        )
    return registry


@pytest.fixture
def runtime():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    from phase4.council.store import CouncilStore

    return sessions, CouncilStore(sessions)


@pytest.fixture
def hypothesis():
    return Hypothesis(
        hypothesis_id="hyp-plan-1",
        task_id="task-plan-1",
        statement="Route frozen assignments through the provider router",
        confidence=0.6,
        status=HypothesisStatus.ACTIVE,
    )


@pytest.fixture
def binding():
    return CouncilSessionBinding(
        organization_id="org-1",
        context_packet_id="context-1",
        hypothesis_revision="hyp-rev-1",
        workspace_revision="git-rev-1",
    )


@pytest.fixture
def agenda():
    return CouncilAgenda.create(
        task_id="task-plan-1",
        context_packet_id="context-1",
        objective="Bind the orchestrator to frozen assignment plans",
        requested_action="patch.apply",
        resource="phase4/council/routing.py",
        affected_files=("phase4/council/orchestrator.py",),
    )


def _approve_script(hypothesis_id: str):
    script = {}
    evidence = Evidence(
        evidence_id="evidence-plan-1",
        hypothesis_id=hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.35,
        source="router_spec_test",
        description="Provider router determinism is proven by frozen snapshots",
    )
    for role in (
        CouncilRole.PROPOSER,
        CouncilRole.ARCHITECT,
        CouncilRole.SECURITY_SKEPTIC,
        CouncilRole.QA_REDTEAM,
    ):
        script[(1, role, CouncilTurnKind.REVIEW)] = CouncilTurnDecision(
            assessment=f"{role.value} approves the plan-driven design.",
            approved=True,
        )
    script[(1, CouncilRole.PROPOSER, CouncilTurnKind.PROPOSAL)] = (
        CouncilTurnDecision(
            assessment="Plan-driven proposal is deterministic.",
            evidence=(evidence,),
        )
    )
    return script


def _route(role: CouncilRole, identity: str | None = None) -> AssignmentRoute:
    return AssignmentRoute(
        assignment_id=f"asg-{role.value}",
        role=role,
        agent_identity=identity or f"plan-{role.value}",
        capability="council." + role.value,
        provider_id="provider-1",
        connection_id="conn-1",
        connection_version=1,
        deployment_id="deploy-1",
        deployment_revision=1,
        model_id="model-1",
        model_family="model-family-1",
        prompt_version="v1",
        protocol_function=ProtocolFunction.REVIEWER,
        route_fingerprint=f"fp-{role.value}",
    )


def _full_plan(*, duplicate_proposer: bool = False) -> CouncilAssignmentPlan:
    proposer_identity = "plan-duplicate" if duplicate_proposer else None
    routes = (
        _route(CouncilRole.PROPOSER, proposer_identity),
        _route(CouncilRole.ARCHITECT, "plan-duplicate" if duplicate_proposer else None),
        _route(CouncilRole.SECURITY_SKEPTIC),
        _route(CouncilRole.QA_REDTEAM),
    )
    return CouncilAssignmentPlan(
        run_id="run-plan-1",
        decision_id="decision-plan-1",
        organization_id="org-1",
        template_id="template-1",
        template_version=1,
        routes=routes,
        plan_fingerprint="fp-plan-1",
    )


def test_plan_drives_roles_and_produces_readiness(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    provider = DeterministicFakeCouncilProvider(_approve_script(hypothesis.hypothesis_id))
    result = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
        legacy_assignments=False,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        assignment_plan=_full_plan(),
        session_id="session-plan-1",
    )
    assert result.outcome is CouncilOrchestrationOutcome.DECISION_READY
    assert result.readiness is not None
    assert result.readiness.is_decision_ready is True


def test_plan_missing_role_fails_closed(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    provider = DeterministicFakeCouncilProvider(_approve_script(hypothesis.hypothesis_id))
    orchestrator = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
        legacy_assignments=False,
    )
    missing = _full_plan()
    missing = CouncilAssignmentPlan(
        run_id=missing.run_id,
        decision_id=missing.decision_id,
        organization_id=missing.organization_id,
        template_id=missing.template_id,
        template_version=missing.template_version,
        routes=tuple(r for r in missing.routes if r.role is not CouncilRole.ARCHITECT),
        plan_fingerprint=missing.plan_fingerprint,
    )
    with pytest.raises(CouncilStartError, match="does not cover"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            assignment_plan=missing,
            session_id="session-plan-missing",
        )


def test_plan_distinct_agent_identities_required(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    provider = DeterministicFakeCouncilProvider(_approve_script(hypothesis.hypothesis_id))
    orchestrator = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
        legacy_assignments=False,
    )
    # Plan with two assignments for the same identity: must fail closed.
    duplicate = _full_plan(duplicate_proposer=True)
    with pytest.raises(CouncilStartError, match="distinct agent identities"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            assignment_plan=duplicate,
            session_id="session-plan-dup",
        )
