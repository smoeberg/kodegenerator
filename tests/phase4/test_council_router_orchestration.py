"""End-to-end: router + plan + orchestrator run a full deliberation."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.council import CouncilOrchestrator, CouncilSessionBinding
from phase4.council.configuration import ProtocolFunction
from phase4.council.orchestrator import CouncilProvider
from phase4.council.roles import (
    ROLE_PERSONAS,
    CouncilAgenda,
    CouncilRole,
    CouncilTurnDecision,
    CouncilTurnKind,
)
from phase4.council.routing import (
    AssignmentRoute,
    CouncilAssignmentPlan,
    TemplateCouncilProviderRouter,
)
from phase4.council.testing import DeterministicFakeCouncilProvider
from phase4.epistemics import Evidence, EvidenceType, Hypothesis, HypothesisStatus


def _capability(name: str) -> Capability:
    return Capability.create(name, AgentVersion(1, 0, 0))


def _registry() -> AgentRegistry:
    registry = AgentRegistry()
    for instance_id, capability in (
        ("proposer", "council.propose"),
        ("architect", "council.review.architecture"),
        ("security", "council.review.security"),
        ("qa", "council.review.qa"),
    ):
        registry.register(
            agent_type=f"council-{instance_id}",
            instance_id=instance_id,
            version=AgentVersion(1, 0, 0),
            role=AgentRole.AUDITOR,
            capabilities=(_capability(capability),),
        )
    return registry


def _route(role: CouncilRole, identity: str) -> AssignmentRoute:
    import hashlib

    def digest(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    values = dict(
        assignment_id=digest(f"asg-router-{role.value}"),
        stage_id=role.value,
        role=role,
        agent_identity=identity,
        capability=ROLE_PERSONAS[role].capability,
        provider_id="conn-1",
        bot_profile_id=f"profile-{role.value}",
        bot_profile_version=1,
        profile_fingerprint=digest(f"profile-{role.value}"),
        connection_id="conn-1",
        connection_version=1,
        connection_fingerprint=digest("conn-1"),
        deployment_id="deploy-1",
        deployment_revision=1,
        deployment_fingerprint=digest("deploy-1"),
        model_id="model-1",
        model_family="model-family-1",
        prompt_version="v1",
        protocol_function=(
            ProtocolFunction.PROPOSER
            if role is CouncilRole.PROPOSER
            else ProtocolFunction.REVIEWER
        ),
    )
    return AssignmentRoute(**values, route_fingerprint=digest(str(values)))


def _approve_script(hypothesis_id: str):
    script = {}
    evidence = Evidence(
        evidence_id="evidence-router-1",
        hypothesis_id=hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.35,
        source="router_spec_test",
        description="Frozen snapshot identities drive provider resolution",
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
    script[(1, CouncilRole.PROPOSER, CouncilTurnKind.PROPOSAL)] = CouncilTurnDecision(
        assessment="Plan-driven proposal is deterministic.",
        evidence=(evidence,),
    )
    return script


class RecordingFactory:
    """Provider factory that records the snapshot identity it was given."""

    def __init__(self, target: CouncilProvider) -> None:
        self._target = target
        self.created: list[dict] = []

    def create(self, **identity) -> CouncilProvider:
        self.created.append(identity)
        return self._target


def _plan() -> CouncilAssignmentPlan:
    routes = (
        _route(CouncilRole.PROPOSER, "router-proposer"),
        _route(CouncilRole.ARCHITECT, "router-architect"),
        _route(CouncilRole.SECURITY_SKEPTIC, "router-security"),
        _route(CouncilRole.QA_REDTEAM, "router-qa"),
    )
    decision_id = "d" * 64
    return CouncilAssignmentPlan(
        run_id="run-router-1",
        decision_id=decision_id,
        organization_id="org-1",
        template_id="template-1",
        template_version=1,
        routes=routes,
        plan_fingerprint=CouncilAssignmentPlan._fingerprint(
            decision_id, "org-1", "template-1", 1, routes
        ),
    )


def test_router_forwards_frozen_snapshot_and_orchestrator_uses_plan() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    from phase4.council.store import CouncilStore

    store = CouncilStore(sessions)
    hypothesis = Hypothesis(
        hypothesis_id="hyp-router-1",
        task_id="task-router-1",
        statement="Route through the plan",
        confidence=0.6,
        status=HypothesisStatus.ACTIVE,
    )
    agenda = CouncilAgenda.create(
        task_id="task-router-1",
        context_packet_id="context-router-1",
        objective="Route via frozen assignments",
        requested_action="patch.apply",
        resource="phase4/council/routing.py",
        affected_files=("phase4/council/orchestrator.py",),
    )
    binding = CouncilSessionBinding(
        organization_id="org-1",
        context_packet_id="context-router-1",
        hypothesis_revision="hyp-rev-1",
        workspace_revision="git-rev-1",
    )
    provider = DeterministicFakeCouncilProvider(
        _approve_script(hypothesis.hypothesis_id),
        provider_id="conn-1",
    )
    factory = RecordingFactory(provider)
    router = TemplateCouncilProviderRouter({"conn-1": factory})

    plan = _plan()
    # The orchestrator must receive the SAME provider the router resolved.
    resolved = router.resolve(plan.route_for(CouncilRole.PROPOSER))
    assert resolved is provider
    assert len(factory.created) == 1
    assert factory.created[0]["deployment_id"] == "deploy-1"
    assert factory.created[0]["route_fingerprint"] == plan.routes[0].route_fingerprint

    result = CouncilOrchestrator(
        registry=_registry(),
        provider_router=router,
        store=store,
        legacy_assignments=False,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        assignment_plan=plan,
        session_id="session-router-1",
    )
    from phase4.council import CouncilOrchestrationOutcome

    assert result.outcome is CouncilOrchestrationOutcome.DECISION_READY
