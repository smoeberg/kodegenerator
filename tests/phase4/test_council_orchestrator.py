"""Contract tests for the durable, fail-closed Council orchestrator."""

from __future__ import annotations

import ast
import inspect

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.adaptation import ExecutionFailure, StrategyFingerprinter
from phase4.agent_registry import AgentRegistry, AgentRole, AgentVersion, Capability
from phase4.authority import RiskLevel
from phase4.council import (
    CouncilAgenda,
    CouncilDisputeProposal,
    CouncilDisputeResolution,
    CouncilFailureEventHandler,
    CouncilOrchestrationOutcome,
    CouncilOrchestrator,
    CouncilProviderError,
    CouncilRole,
    CouncilRuntimeEventType,
    CouncilSessionBinding,
    CouncilStartError,
    CouncilStore,
    CouncilTurnDecision,
    CouncilTurnKind,
    CouncilTurnRequest,
    CouncilTurnResponse,
    DeliberationConfig,
    DeliberationSession,
    ExecutionFailedEvent,
    SessionState,
)
from phase4.council.testing import DeterministicFakeCouncilProvider
from phase4.epistemics import Evidence, EvidenceType, Hypothesis, HypothesisStatus


def _capability(name: str) -> Capability:
    return Capability.create(name, AgentVersion(1, 0, 0))


def _registry(*, include_qa: bool = True) -> AgentRegistry:
    registry = AgentRegistry()
    declarations = [
        ("proposer", "council.propose"),
        ("architect", "council.review.architecture"),
        ("security", "council.review.security"),
    ]
    if include_qa:
        declarations.append(("qa", "council.review.qa"))
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
    return sessions, CouncilStore(sessions)


@pytest.fixture
def hypothesis():
    return Hypothesis(
        hypothesis_id="hyp-orchestrator-1",
        task_id="task-orchestrator-1",
        statement="Use a bounded worker pool for report generation",
        confidence=0.55,
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
        task_id="task-orchestrator-1",
        context_packet_id="context-1",
        objective="Remove unbounded report generation concurrency",
        requested_action="patch.apply",
        resource="reports/worker_pool.py",
        affected_files=("reports/worker_pool.py", "tests/test_worker_pool.py"),
    )


def _evidence(
    hypothesis_id: str, evidence_id: str = "evidence-bounded-pool"
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        hypothesis_id=hypothesis_id,
        evidence_type=EvidenceType.SUPPORTING,
        weight=0.35,
        source="bounded_pool_test",
        description="Concurrency test proves the configured worker limit is enforced",
    )


def _approve_script(hypothesis_id: str, *, rounds: tuple[int, ...] = (1,)):
    script = {}
    evidence = _evidence(hypothesis_id)
    for round_number in rounds:
        script[(round_number, CouncilRole.PROPOSER, CouncilTurnKind.PROPOSAL)] = (
            CouncilTurnDecision(
                assessment="The bounded design is supported by deterministic tests.",
                evidence=(evidence,),
            )
        )
        for role in (
            CouncilRole.ARCHITECT,
            CouncilRole.SECURITY_SKEPTIC,
            CouncilRole.QA_REDTEAM,
        ):
            script[(round_number, role, CouncilTurnKind.REVIEW)] = CouncilTurnDecision(
                assessment=f"{role.value} assessment approves the bounded design.",
                approved=True,
            )
    return script


def test_full_cycle_persists_and_returns_readiness(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    provider = DeterministicFakeCouncilProvider(
        _approve_script(hypothesis.hypothesis_id)
    )
    orchestrator = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
    )

    result = orchestrator.run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        session_id="session-happy",
    )

    assert result.outcome is CouncilOrchestrationOutcome.DECISION_READY
    assert result.final_state is SessionState.DECISION_READY
    assert result.readiness is not None
    assert result.readiness.is_decision_ready is True
    assert result.readiness.evidence_verified is True
    assert result.readiness.evaluated_revision == binding.workspace_revision
    assert result.risk_level is RiskLevel.LOW
    assert len({assignment.agent_identity for assignment in result.assignments}) == 4
    persisted = store.get(binding.organization_id, result.session_id)
    assert persisted is not None
    assert persisted.state_version == 1
    assert store.evidence_revision_map(binding.organization_id, result.session_id) == {
        "evidence-bounded-pool": binding.workspace_revision
    }


def test_vote_consensus_without_evidence_is_readiness_blocked(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    script = _approve_script(hypothesis.hypothesis_id)
    script[(1, CouncilRole.PROPOSER, CouncilTurnKind.PROPOSAL)] = CouncilTurnDecision(
        assessment="No evidence was produced."
    )

    result = CouncilOrchestrator(
        registry=_registry(),
        provider=DeterministicFakeCouncilProvider(script),
        store=store,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        session_id="session-no-evidence",
    )

    assert result.final_state is SessionState.DECISION_READY
    assert result.outcome is CouncilOrchestrationOutcome.READINESS_BLOCKED
    assert result.readiness is not None
    assert result.readiness.is_decision_ready is False
    assert result.readiness.evidence_verified is False


def test_required_role_is_fail_closed_before_session_creation(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    provider = DeterministicFakeCouncilProvider({})
    orchestrator = CouncilOrchestrator(
        registry=_registry(include_qa=False),
        provider=provider,
        store=store,
    )

    with pytest.raises(CouncilStartError, match="qa_redteam"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            session_id="session-missing-role",
        )

    assert store.get(binding.organization_id, "session-missing-role") is None
    assert provider.calls == ()


def test_one_agent_cannot_fill_independent_roles(runtime, hypothesis, binding, agenda):
    _, store = runtime
    registry = AgentRegistry()
    registry.register(
        agent_type="multi-role",
        instance_id="multi",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.AUDITOR,
        capabilities=(
            _capability("council.propose"),
            _capability("council.review.architecture"),
        ),
    )
    for instance_id, capability in (
        ("security", "council.review.security"),
        ("qa", "council.review.qa"),
    ):
        registry.register(
            agent_type=instance_id,
            instance_id=instance_id,
            version=AgentVersion(1, 0, 0),
            role=AgentRole.AUDITOR,
            capabilities=(_capability(capability),),
        )
    orchestrator = CouncilOrchestrator(
        registry=registry,
        provider=DeterministicFakeCouncilProvider({}),
        store=store,
    )

    with pytest.raises(CouncilStartError, match="distinct agent identities"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            session_id="session-duplicate-agent",
        )


def test_security_dispute_requires_evidence_and_derives_high_risk(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    resolution_evidence = _evidence(
        hypothesis.hypothesis_id,
        "evidence-security-resolution",
    )
    script = _approve_script(hypothesis.hypothesis_id)
    script[(1, CouncilRole.SECURITY_SKEPTIC, CouncilTurnKind.REVIEW)] = (
        CouncilTurnDecision(
            assessment="Worker identity isolation was not demonstrated.",
            approved=False,
            disputes=(
                CouncilDisputeProposal(
                    reason="Worker identity isolation lacks revision-bound evidence"
                ),
            ),
        )
    )
    provider = DeterministicFakeCouncilProvider(script)

    class ResolutionProvider:
        provider_id = provider.provider_id

        def deliberate(self, request):
            if request.turn_kind is CouncilTurnKind.DISPUTE_RESOLUTION:
                return CouncilTurnResponse(
                    turn_id=request.turn_id,
                    agent_identity=request.agent_identity,
                    role=request.role,
                    assessment="Isolation is proven by the organization-bound worker test.",
                    resolutions=tuple(
                        CouncilDisputeResolution(
                            dispute_id=dispute.dispute_id,
                            evidence=resolution_evidence,
                            resolution_note="Verified by the organization isolation suite",
                        )
                        for dispute in request.open_disputes
                    ),
                )
            return provider.deliberate(request)

    result = CouncilOrchestrator(
        registry=_registry(),
        provider=ResolutionProvider(),
        store=store,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        session_id="session-dispute",
    )

    assert result.outcome is CouncilOrchestrationOutcome.DECISION_READY
    assert result.risk_level is RiskLevel.HIGH
    assert result.readiness is not None
    assert result.readiness.total_disputes == 1
    assert result.readiness.open_critical_disputes == 0
    assert result.readiness.evidence_verified is True


def test_unresolved_dispute_aborts_round_without_partial_persistence(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    script = _approve_script(hypothesis.hypothesis_id)
    script[(1, CouncilRole.SECURITY_SKEPTIC, CouncilTurnKind.REVIEW)] = (
        CouncilTurnDecision(
            assessment="Isolation evidence is missing.",
            approved=False,
            disputes=(CouncilDisputeProposal(reason="Isolation evidence is missing"),),
        )
    )
    script[(1, CouncilRole.PROPOSER, CouncilTurnKind.DISPUTE_RESOLUTION)] = (
        CouncilTurnDecision(assessment="No evidence is currently available.")
    )
    provider = DeterministicFakeCouncilProvider(script)
    orchestrator = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
    )

    with pytest.raises(CouncilProviderError, match="bounded retries"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            session_id="session-unresolved",
        )

    with pytest.raises(CouncilProviderError, match="bounded retries"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            session_id="session-unresolved",
        )

    resolution_requests = tuple(
        request
        for request in provider.calls
        if request.turn_kind is CouncilTurnKind.DISPUTE_RESOLUTION
    )
    assert len(resolution_requests) == 4
    assert len({request.turn_id for request in resolution_requests}) == 1
    assert (
        len({request.open_disputes[0].dispute_id for request in resolution_requests})
        == 1
    )

    persisted = store.get(binding.organization_id, "session-unresolved")
    assert persisted is not None
    assert persisted.state_version == 0
    assert persisted.session.state is SessionState.OPEN
    assert persisted.session.votes[1] == []
    assert persisted.session.hypothesis.supporting_evidence == []


def test_provider_binding_mismatch_retries_then_fails_closed(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime

    class ForgingProvider:
        provider_id = "fake.forging"

        def __init__(self):
            self.calls = 0

        def deliberate(self, request):
            self.calls += 1
            return CouncilTurnResponse(
                turn_id=request.turn_id,
                agent_identity="forged-agent",
                role=request.role,
                assessment="forged",
            )

    provider = ForgingProvider()
    orchestrator = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
    )

    with pytest.raises(CouncilProviderError, match="bounded retries"):
        orchestrator.run(
            hypothesis=hypothesis,
            binding=binding,
            agenda=agenda,
            session_id="session-forged",
        )

    assert provider.calls == 2
    persisted = store.get(binding.organization_id, "session-forged")
    assert persisted is not None
    assert persisted.state_version == 0


def test_round_checkpoint_recovers_with_new_orchestrator_instance(
    runtime, hypothesis, binding, agenda
):
    _, store = runtime
    script = _approve_script(hypothesis.hypothesis_id, rounds=(1, 2))
    for round_number in (1, 2):
        script[(round_number, CouncilRole.QA_REDTEAM, CouncilTurnKind.REVIEW)] = (
            CouncilTurnDecision(
                assessment="The acceptance boundary remains incomplete.",
                approved=False,
                disputes=(
                    CouncilDisputeProposal(
                        reason=f"Round {round_number} acceptance evidence is incomplete"
                    ),
                ),
            )
        )

    class ResolvingProvider:
        provider_id = "fake.council.recovery"

        def __init__(self):
            self.scripted = DeterministicFakeCouncilProvider(
                script,
                provider_id=self.provider_id,
            )

        def deliberate(self, request):
            if request.turn_kind is CouncilTurnKind.DISPUTE_RESOLUTION:
                return CouncilTurnResponse(
                    turn_id=request.turn_id,
                    agent_identity=request.agent_identity,
                    role=request.role,
                    assessment="The dispute was tested but the reviewer may retain its vote.",
                    resolutions=tuple(
                        CouncilDisputeResolution(
                            dispute_id=dispute.dispute_id,
                            evidence=_evidence(
                                hypothesis.hypothesis_id,
                                f"resolution-{request.round_number}-{dispute.dispute_id}",
                            ),
                            resolution_note="Resolution evidence is revision-bound",
                        )
                        for dispute in request.open_disputes
                    ),
                )
            return self.scripted.deliberate(request)

    config = DeliberationConfig(max_rounds=2, approval_threshold=1.0)
    first = CouncilOrchestrator(
        registry=_registry(),
        provider=ResolvingProvider(),
        store=store,
        config=config,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        session_id="session-recovery",
        round_budget=1,
    )
    assert first.outcome is CouncilOrchestrationOutcome.IN_PROGRESS
    assert first.final_state is SessionState.OPEN
    assert first.state_version == 1

    second = CouncilOrchestrator(
        registry=_registry(),
        provider=ResolvingProvider(),
        store=store,
        config=config,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        session_id="session-recovery",
    )

    assert second.outcome is CouncilOrchestrationOutcome.HUMAN_REQUIRED
    assert second.final_state is SessionState.DEADLOCKED
    assert second.state_version == 2
    events = store.pending_events(binding.organization_id)
    assert CouncilRuntimeEventType.HUMAN_REQUIRED in {
        event.event_type for event in events
    }


def test_pending_anti_tube_pivot_preempts_provider(
    runtime, hypothesis, binding, agenda
):
    sessions, store = runtime
    session = DeliberationSession(hypothesis, session_id="session-pivot")
    store.create(session, binding)
    fingerprint = StrategyFingerprinter.create(
        hypothesis_id=hypothesis.hypothesis_id,
        affected_files=list(agenda.affected_files),
        change_pattern="bounded worker pool",
    )
    handler = CouncilFailureEventHandler(sessions)
    for execution_id in ("exec-1", "exec-2"):
        failure = ExecutionFailure(
            failure_id=execution_id,
            task_id=hypothesis.task_id,
            error_type="AssertionError",
            error_message="worker count exceeded limit",
            failed_tests=["test_worker_limit"],
        )
        handler.handle(
            ExecutionFailedEvent.create(
                organization_id=binding.organization_id,
                session_id=session.session_id,
                hypothesis_id=hypothesis.hypothesis_id,
                hypothesis_revision=binding.hypothesis_revision,
                workspace_revision=binding.workspace_revision,
                context_packet_id=binding.context_packet_id,
                execution_id=execution_id,
                fingerprint=fingerprint,
                failure=failure,
            )
        )

    pivot_event = next(
        event
        for event in store.pending_events(binding.organization_id)
        if event.event_type is CouncilRuntimeEventType.PIVOT_REQUIRED
    )
    store.mark_published(binding.organization_id, pivot_event.event_id)

    provider = DeterministicFakeCouncilProvider({})
    result = CouncilOrchestrator(
        registry=_registry(),
        provider=provider,
        store=store,
    ).run(
        hypothesis=hypothesis,
        binding=binding,
        agenda=agenda,
        session_id=session.session_id,
    )

    assert result.outcome is CouncilOrchestrationOutcome.PIVOT_REQUIRED
    assert result.readiness is None
    assert provider.calls == ()


def test_agenda_and_turn_identity_reject_tampering(hypothesis, binding, agenda):
    forged_agenda = agenda.model_dump()
    forged_agenda["resource"] = "authority/engine.py"
    with pytest.raises(ValidationError, match="agenda digest"):
        CouncilAgenda.model_validate(forged_agenda)

    request = CouncilTurnRequest.create(
        provider_id="fake",
        session_id="session-1",
        round_number=1,
        turn_kind=CouncilTurnKind.PROPOSAL,
        role=CouncilRole.PROPOSER,
        agent_identity="agent-1",
        binding=binding,
        agenda=agenda,
        hypothesis=hypothesis,
    )
    forged_request = request.model_dump()
    forged_request["round_number"] = 2
    with pytest.raises(ValidationError, match="turn digest"):
        type(request).model_validate(forged_request)


def test_orchestrator_has_no_authority_or_execution_capability():
    source = inspect.getsource(CouncilOrchestrator)
    tree = ast.parse(source)
    run_parameters = inspect.signature(CouncilOrchestrator.run).parameters
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "AuthorityEngine" not in names
    assert "issue_grant" not in attributes
    assert not any(module.startswith("phase4.execution") for module in imported_modules)
    assert "risk_level" not in run_parameters
