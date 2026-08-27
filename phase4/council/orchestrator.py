"""Durable, fail-closed orchestration of dialectical Council rounds."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

from pydantic import BaseModel, ConfigDict, Field

from phase4.agent_registry import AgentRegistry
from phase4.epistemics.models import Evidence, EvidenceType, Hypothesis

from .models import Dispute, SessionState
from .roles import (
    ROLE_PERSONAS,
    CouncilAgenda,
    CouncilOrchestrationOutcome,
    CouncilRole,
    CouncilRoleAssignment,
    CouncilTurnKind,
    CouncilTurnRequest,
    CouncilTurnResponse,
)
from .runtime_models import CouncilRuntimeEventType, CouncilSessionBinding
from .session import DeliberationSession
from .store import CouncilConflictError, CouncilStore

if TYPE_CHECKING:
    from phase4.authority.adapter import DecisionReadiness, RiskLevel
else:
    DecisionReadiness = Any
    RiskLevel = Any


class CouncilOrchestrationError(RuntimeError):
    """Base fail-closed Council orchestration error."""


class CouncilStartError(CouncilOrchestrationError):
    """Raised before a Council can start with incomplete or forged inputs."""


class CouncilProviderError(CouncilOrchestrationError):
    """Raised when a provider cannot produce a valid, bound response."""


class CouncilProviderResponseError(CouncilProviderError):
    """Raised when provider output violates its turn contract."""


class CouncilProvider(Protocol):
    """Opaque deliberation provider; it has no Authority or Execution capability."""

    @property
    def provider_id(self) -> str: ...

    def deliberate(self, request: CouncilTurnRequest) -> CouncilTurnResponse: ...


class CouncilRiskEvaluator(Protocol):
    """Derive risk from the immutable agenda and completed Council record."""

    def evaluate(
        self,
        agenda: CouncilAgenda,
        session: DeliberationSession,
        assignments: tuple[CouncilRoleAssignment, ...],
    ) -> RiskLevel: ...


class DefaultCouncilRiskEvaluator:
    """Conservative deterministic risk policy with no caller-supplied level."""

    _CRITICAL_ACTIONS: ClassVar[frozenset[str]] = frozenset(
        {
            "authority.override",
            "policy.disable",
            "secrets.export",
            "security.bypass",
        }
    )
    _HIGH_RISK_MARKERS = (
        "auth",
        "authority",
        "security",
        "secret",
        "execution",
        "alembic",
        ".github/workflows",
    )

    def evaluate(
        self,
        agenda: CouncilAgenda,
        session: DeliberationSession,
        assignments: tuple[CouncilRoleAssignment, ...],
    ) -> RiskLevel:
        from phase4.authority.adapter import RiskLevel

        if agenda.requested_action.lower() in self._CRITICAL_ACTIONS:
            return RiskLevel.CRITICAL
        resources = (agenda.resource, *agenda.affected_files)
        normalized = tuple(item.lower() for item in resources)
        if any(
            marker in item for marker in self._HIGH_RISK_MARKERS for item in normalized
        ):
            return RiskLevel.HIGH
        security_identity = next(
            assignment.agent_identity
            for assignment in assignments
            if assignment.role is CouncilRole.SECURITY_SKEPTIC
        )
        disputes = tuple(session.dispute_protocol._disputes.values())
        if any(dispute.raised_by_agent_id == security_identity for dispute in disputes):
            return RiskLevel.HIGH
        if disputes or len(agenda.affected_files) > 3:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


class DeliberationConfig(BaseModel):
    """Bounded runtime policy; required roles cannot be weakened by configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_rounds: int = Field(default=4, ge=1, le=20)
    approval_threshold: float = Field(default=0.6, gt=0.0, le=1.0)
    provider_retry_limit: int = Field(default=1, ge=0, le=3)
    minimum_evidence: int = Field(default=1, ge=1, le=100)


@dataclass(frozen=True)
class CouncilOrchestratorResult:
    """Terminal or checkpoint result; never an Authority grant."""

    session_id: str
    final_state: SessionState
    outcome: CouncilOrchestrationOutcome
    state_version: int
    assignments: tuple[CouncilRoleAssignment, ...]
    rounds_completed: int
    provider_id: str
    readiness: DecisionReadiness | None = None
    risk_level: RiskLevel | None = None


class CouncilOrchestrator:
    """Run evidence-backed Council rounds and persist one atomic round at a time.

    The orchestrator selects registered agents, invokes a provider through
    content-addressed turns, persists completed rounds with OCC, and returns a
    readiness report. It never imports or calls AuthorityEngine or Execution.
    """

    _REQUIRED_ROLES = (
        CouncilRole.PROPOSER,
        CouncilRole.ARCHITECT,
        CouncilRole.SECURITY_SKEPTIC,
        CouncilRole.QA_REDTEAM,
    )
    _PREEMPTION: ClassVar[
        dict[CouncilRuntimeEventType, CouncilOrchestrationOutcome]
    ] = {
        CouncilRuntimeEventType.POLICY_ESCALATION_REQUIRED: (
            CouncilOrchestrationOutcome.POLICY_ESCALATION_REQUIRED
        ),
        CouncilRuntimeEventType.ENVIRONMENT_HALT_REQUIRED: (
            CouncilOrchestrationOutcome.ENVIRONMENT_HALT_REQUIRED
        ),
        CouncilRuntimeEventType.PIVOT_REQUIRED: (
            CouncilOrchestrationOutcome.PIVOT_REQUIRED
        ),
        CouncilRuntimeEventType.HUMAN_REQUIRED: (
            CouncilOrchestrationOutcome.HUMAN_REQUIRED
        ),
    }

    def __init__(
        self,
        *,
        registry: AgentRegistry,
        provider: CouncilProvider,
        store: CouncilStore,
        config: DeliberationConfig | None = None,
        risk_evaluator: CouncilRiskEvaluator | None = None,
    ) -> None:
        provider_id = getattr(provider, "provider_id", None)
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise TypeError("provider must declare a non-empty provider_id")
        if not callable(getattr(provider, "deliberate", None)):
            raise TypeError("provider must implement deliberate")
        self.registry = registry
        self.provider = provider
        self.provider_id = provider_id
        self.store = store
        self.config = config or DeliberationConfig()
        self.risk_evaluator = risk_evaluator or DefaultCouncilRiskEvaluator()

    def run(
        self,
        *,
        hypothesis: Hypothesis,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
        session_id: str | None = None,
        round_budget: int | None = None,
    ) -> CouncilOrchestratorResult:
        if round_budget is not None and round_budget < 1:
            raise CouncilStartError("round_budget must be at least 1")
        self._verify_start_inputs(hypothesis, binding, agenda)
        assignments = self._select_assignments()
        persisted = self._load_or_create(hypothesis, binding, session_id)
        self._verify_persisted_binding(persisted.binding, binding)
        self._verify_hypothesis_identity(persisted.session.hypothesis, hypothesis)

        preempted = self._preempted_result(persisted, assignments)
        if preempted is not None:
            return preempted
        terminal = self._terminal_result(persisted, agenda, assignments)
        if terminal is not None:
            return terminal

        session = persisted.session
        version = persisted.state_version
        completed = 0
        while session.state not in (
            SessionState.DECISION_READY,
            SessionState.DEADLOCKED,
        ):
            if round_budget is not None and completed >= round_budget:
                break
            self._run_round(session, binding, agenda, assignments)
            version = self.store.save(
                binding.organization_id,
                session,
                expected_version=version,
            )
            completed += 1

        refreshed = self.store.get(binding.organization_id, session.session_id)
        if refreshed is None:
            raise CouncilConflictError("council session disappeared after durable save")
        preempted = self._preempted_result(refreshed, assignments, completed)
        if preempted is not None:
            return preempted
        terminal = self._terminal_result(refreshed, agenda, assignments, completed)
        if terminal is not None:
            return terminal
        return CouncilOrchestratorResult(
            session_id=refreshed.session.session_id,
            final_state=refreshed.session.state,
            outcome=CouncilOrchestrationOutcome.IN_PROGRESS,
            state_version=refreshed.state_version,
            assignments=assignments,
            rounds_completed=completed,
            provider_id=self.provider_id,
        )

    def _run_round(
        self,
        session: DeliberationSession,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
        assignments: tuple[CouncilRoleAssignment, ...],
    ) -> None:
        proposer = self._assignment(assignments, CouncilRole.PROPOSER)
        open_disputes = self._open_disputes(session)
        if open_disputes:
            self._resolve_disputes(session, binding, agenda, proposer, open_disputes)

        proposal = self._invoke(
            self._request(
                session,
                binding,
                agenda,
                proposer,
                CouncilTurnKind.PROPOSAL,
            ),
            validator=self._validate_proposal,
        )
        self._incorporate_evidence(session, proposal.evidence)

        reviewer_responses: list[CouncilTurnResponse] = []
        for role in self._REQUIRED_ROLES[1:]:
            assignment = self._assignment(assignments, role)
            response = self._invoke(
                self._request(
                    session,
                    binding,
                    agenda,
                    assignment,
                    CouncilTurnKind.REVIEW,
                ),
                validator=self._validate_review,
            )
            self._incorporate_evidence(session, response.evidence)
            for index, dispute in enumerate(response.disputes):
                dispute_id = hashlib.sha256(
                    f"{response.turn_id}\x1f{index}".encode()
                ).hexdigest()
                session.raise_dispute(
                    assignment.agent_identity,
                    dispute.reason,
                    dispute_id=dispute_id,
                )
            reviewer_responses.append(response)

        open_disputes = self._open_disputes(session)
        if open_disputes:
            self._resolve_disputes(session, binding, agenda, proposer, open_disputes)
        if self._open_disputes(session):
            raise CouncilProviderResponseError(
                "provider left formal disputes unresolved"
            )

        existing_voters = {
            vote.agent_id for vote in session.votes.get(session.current_round, [])
        }
        for response in reviewer_responses:
            if response.agent_identity in existing_voters:
                continue
            session.cast_vote(
                response.agent_identity,
                bool(response.approved),
                response.assessment,
            )
        session.conclude_round()

    def _resolve_disputes(
        self,
        session: DeliberationSession,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
        proposer: CouncilRoleAssignment,
        disputes: tuple[Dispute, ...],
    ) -> None:
        response = self._invoke(
            self._request(
                session,
                binding,
                agenda,
                proposer,
                CouncilTurnKind.DISPUTE_RESOLUTION,
                open_disputes=disputes,
            ),
            validator=lambda candidate: self._validate_resolution(
                candidate,
                session,
                disputes,
            ),
        )
        for resolution in response.resolutions:
            session.resolve_dispute(
                resolution.dispute_id,
                resolution.evidence,
                resolution.resolution_note,
            )

    def _invoke(
        self,
        request: CouncilTurnRequest,
        *,
        validator: Callable[[CouncilTurnResponse], None] | None = None,
    ) -> CouncilTurnResponse:
        last_error: Exception | None = None
        for _ in range(self.config.provider_retry_limit + 1):
            try:
                response = self.provider.deliberate(request)
                if not isinstance(response, CouncilTurnResponse):
                    raise CouncilProviderResponseError(
                        "provider returned an unsupported response type"
                    )
                if (
                    response.turn_id != request.turn_id
                    or response.agent_identity != request.agent_identity
                    or response.role is not request.role
                ):
                    raise CouncilProviderResponseError(
                        "provider response is not bound to the requested turn"
                    )
                if validator is not None:
                    validator(response)
                return response
            except Exception as exc:  # noqa: BLE001 - opaque provider boundary
                last_error = exc
        raise CouncilProviderError(
            f"provider failed turn {request.turn_id} after bounded retries"
        ) from last_error

    @staticmethod
    def _validate_proposal(response: CouncilTurnResponse) -> None:
        if response.approved is not None or response.disputes or response.resolutions:
            raise CouncilProviderResponseError(
                "proposal turn may only return assessment and evidence"
            )

    @staticmethod
    def _validate_review(response: CouncilTurnResponse) -> None:
        if response.approved is None or response.resolutions:
            raise CouncilProviderResponseError("review turn requires a bound vote")
        if response.approved and response.disputes:
            raise CouncilProviderResponseError(
                "an approving review cannot raise a formal dispute"
            )
        if not response.approved and not response.disputes:
            raise CouncilProviderResponseError(
                "a rejecting review must raise a formal dispute"
            )

    @staticmethod
    def _validate_resolution(
        response: CouncilTurnResponse,
        session: DeliberationSession,
        disputes: tuple[Dispute, ...],
    ) -> None:
        expected = {dispute.dispute_id for dispute in disputes}
        actual = {resolution.dispute_id for resolution in response.resolutions}
        if response.approved is not None or response.disputes or response.evidence:
            raise CouncilProviderResponseError(
                "dispute resolution turn may only return formal resolutions"
            )
        if actual != expected or len(actual) != len(response.resolutions):
            raise CouncilProviderResponseError(
                "provider must resolve every open dispute exactly once"
            )
        for resolution in response.resolutions:
            evidence = resolution.evidence
            if evidence.hypothesis_id != session.hypothesis.hypothesis_id:
                raise CouncilProviderResponseError(
                    "resolution evidence is bound to another hypothesis"
                )
            if evidence.evidence_type is not EvidenceType.SUPPORTING:
                raise CouncilProviderResponseError(
                    "formal dispute resolution requires supporting evidence"
                )

    @staticmethod
    def _incorporate_evidence(
        session: DeliberationSession,
        evidences: tuple[Evidence, ...],
    ) -> None:
        existing = {
            evidence.evidence_id: evidence
            for evidence in (
                *session.hypothesis.supporting_evidence,
                *session.hypothesis.contradicting_evidence,
            )
        }
        for evidence in evidences:
            if evidence.hypothesis_id != session.hypothesis.hypothesis_id:
                raise CouncilProviderResponseError(
                    "provider evidence is bound to another hypothesis"
                )
            if evidence.evidence_type is EvidenceType.OBSERVATION:
                raise CouncilProviderResponseError(
                    "provider observations require the execution-event boundary"
                )
            previous = existing.get(evidence.evidence_id)
            if previous is not None:
                if previous != evidence:
                    raise CouncilProviderResponseError(
                        "provider reused an evidence ID with changed content"
                    )
                continue
            session.belief_engine.incorporate_evidence(session.hypothesis, evidence)
            existing[evidence.evidence_id] = evidence

    def _request(
        self,
        session: DeliberationSession,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
        assignment: CouncilRoleAssignment,
        turn_kind: CouncilTurnKind,
        *,
        open_disputes: tuple[Dispute, ...] = (),
    ) -> CouncilTurnRequest:
        return CouncilTurnRequest.create(
            provider_id=self.provider_id,
            session_id=session.session_id,
            round_number=session.current_round,
            turn_kind=turn_kind,
            role=assignment.role,
            agent_identity=assignment.agent_identity,
            binding=binding,
            agenda=agenda,
            hypothesis=session.hypothesis,
            open_disputes=open_disputes,
        )

    def _select_assignments(self) -> tuple[CouncilRoleAssignment, ...]:
        assignments: list[CouncilRoleAssignment] = []
        identities: set[str] = set()
        for role in self._REQUIRED_ROLES:
            persona = ROLE_PERSONAS[role]
            candidates = self.registry.list(capability=persona.capability)
            if not candidates:
                raise CouncilStartError(
                    f"required Council role {role.value} has no active registered agent"
                )
            selected = candidates[0]
            identity = str(selected.identity)
            if identity in identities:
                raise CouncilStartError(
                    "independent Council roles must use distinct agent identities"
                )
            identities.add(identity)
            assignments.append(
                CouncilRoleAssignment(
                    role=role,
                    agent_identity=identity,
                    capability=persona.capability,
                )
            )
        return tuple(assignments)

    def _load_or_create(
        self,
        hypothesis: Hypothesis,
        binding: CouncilSessionBinding,
        session_id: str | None,
    ):
        if session_id is not None:
            existing = self.store.get(binding.organization_id, session_id)
            if existing is not None:
                return existing
        session = DeliberationSession(
            hypothesis.model_copy(deep=True),
            max_rounds=self.config.max_rounds,
            approval_threshold=self.config.approval_threshold,
            session_id=session_id,
        )
        return self.store.create(session, binding)

    def _terminal_result(
        self,
        persisted,
        agenda: CouncilAgenda,
        assignments: tuple[CouncilRoleAssignment, ...],
        rounds_completed: int = 0,
    ) -> CouncilOrchestratorResult | None:
        session = persisted.session
        if session.state is SessionState.DEADLOCKED:
            return self._result(
                persisted,
                assignments,
                CouncilOrchestrationOutcome.HUMAN_REQUIRED,
                rounds_completed,
            )
        if session.state is not SessionState.DECISION_READY:
            return None
        from phase4.authority.adapter import CouncilDecisionAdapter

        risk = self.risk_evaluator.evaluate(agenda, session, assignments)
        evidence_map = self.store.evidence_revision_map(
            persisted.binding.organization_id,
            session.session_id,
        )
        readiness = CouncilDecisionAdapter.evaluate(
            session=session,
            current_revision=persisted.binding.workspace_revision,
            risk_level=risk,
            evidence_revision_map=evidence_map,
        )
        if readiness.evidence_count < self.config.minimum_evidence:
            readiness = replace(
                readiness,
                evidence_verified=False,
                is_decision_ready=False,
                summary=(
                    f"{readiness.summary} Minimum evidence requirement "
                    f"({self.config.minimum_evidence}) was not met."
                ),
            )
        outcome = (
            CouncilOrchestrationOutcome.DECISION_READY
            if readiness.is_decision_ready
            else CouncilOrchestrationOutcome.READINESS_BLOCKED
        )
        return self._result(
            persisted,
            assignments,
            outcome,
            rounds_completed,
            readiness=readiness,
            risk_level=risk,
        )

    def _preempted_result(
        self,
        persisted,
        assignments: tuple[CouncilRoleAssignment, ...],
        rounds_completed: int = 0,
    ) -> CouncilOrchestratorResult | None:
        events = self.store.events_for_aggregate(
            persisted.binding.organization_id,
            persisted.session.session_id,
        )
        event_types = {event.event_type for event in events}
        for event_type, outcome in self._PREEMPTION.items():
            if event_type in event_types:
                return self._result(
                    persisted,
                    assignments,
                    outcome,
                    rounds_completed,
                )
        return None

    def _result(
        self,
        persisted,
        assignments: tuple[CouncilRoleAssignment, ...],
        outcome: CouncilOrchestrationOutcome,
        rounds_completed: int,
        *,
        readiness: DecisionReadiness | None = None,
        risk_level: RiskLevel | None = None,
    ) -> CouncilOrchestratorResult:
        return CouncilOrchestratorResult(
            session_id=persisted.session.session_id,
            final_state=persisted.session.state,
            outcome=outcome,
            state_version=persisted.state_version,
            readiness=readiness,
            risk_level=risk_level,
            assignments=assignments,
            rounds_completed=rounds_completed,
            provider_id=self.provider_id,
        )

    @staticmethod
    def _assignment(
        assignments: tuple[CouncilRoleAssignment, ...],
        role: CouncilRole,
    ) -> CouncilRoleAssignment:
        return next(item for item in assignments if item.role is role)

    @staticmethod
    def _open_disputes(session: DeliberationSession) -> tuple[Dispute, ...]:
        return tuple(
            sorted(
                session.dispute_protocol.get_open_disputes_for_hypothesis(
                    session.hypothesis.hypothesis_id
                ),
                key=lambda dispute: dispute.dispute_id,
            )
        )

    @staticmethod
    def _verify_start_inputs(
        hypothesis: Hypothesis,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
    ) -> None:
        if agenda.task_id != hypothesis.task_id:
            raise CouncilStartError("agenda task does not match the hypothesis")
        if agenda.context_packet_id != binding.context_packet_id:
            raise CouncilStartError("agenda does not match the bound context packet")

    @staticmethod
    def _verify_persisted_binding(
        persisted: CouncilSessionBinding,
        requested: CouncilSessionBinding,
    ) -> None:
        if persisted != requested:
            raise CouncilStartError(
                "persisted Council provenance does not match request"
            )

    @staticmethod
    def _verify_hypothesis_identity(
        persisted: Hypothesis,
        requested: Hypothesis,
    ) -> None:
        if (
            persisted.hypothesis_id != requested.hypothesis_id
            or persisted.task_id != requested.task_id
            or persisted.statement != requested.statement
            or persisted.created_at != requested.created_at
        ):
            raise CouncilStartError(
                "persisted hypothesis identity does not match request"
            )
