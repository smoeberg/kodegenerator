"""Provider-neutral contracts for governed Council deliberation turns."""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from phase4.epistemics.models import Evidence, Hypothesis

from .configuration import ProtocolFunction
from .models import Dispute
from .runtime_models import CouncilSessionBinding


class CouncilRole(str, Enum):
    """Independent responsibilities required for a strong Council."""

    PROPOSER = "proposer"
    ARCHITECT = "architect"
    SECURITY_SKEPTIC = "security_skeptic"
    QA_REDTEAM = "qa_redteam"


class CouncilTurnKind(str, Enum):
    PROPOSAL = "proposal"
    REVIEW = "review"
    DISPUTE_RESOLUTION = "dispute_resolution"


class CouncilOrchestrationOutcome(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    DECISION_READY = "DECISION_READY"
    READINESS_BLOCKED = "READINESS_BLOCKED"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    PIVOT_REQUIRED = "PIVOT_REQUIRED"
    ENVIRONMENT_HALT_REQUIRED = "ENVIRONMENT_HALT_REQUIRED"
    POLICY_ESCALATION_REQUIRED = "POLICY_ESCALATION_REQUIRED"


class RolePersona(BaseModel):
    """Immutable role prompt and registry capability binding."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: CouncilRole
    capability: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    must_produce_assessment: bool = True


ROLE_PERSONAS: dict[CouncilRole, RolePersona] = {
    CouncilRole.PROPOSER: RolePersona(
        role=CouncilRole.PROPOSER,
        capability="council.propose",
        system_prompt=(
            "Improve and defend the hypothesis with revision-bound evidence. "
            "Resolve every formal dispute or leave the Council blocked."
        ),
    ),
    CouncilRole.ARCHITECT: RolePersona(
        role=CouncilRole.ARCHITECT,
        capability="council.review.architecture",
        system_prompt=(
            "Assess system boundaries, dependency direction, state transitions, "
            "recovery, and compatibility. Raise a formal dispute for material defects."
        ),
    ),
    CouncilRole.SECURITY_SKEPTIC: RolePersona(
        role=CouncilRole.SECURITY_SKEPTIC,
        capability="council.review.security",
        system_prompt=(
            "Assess authorization, isolation, provenance, concurrency, "
            "resource limits, "
            "secrets, and supply-chain risk. Do not invent findings."
        ),
    ),
    CouncilRole.QA_REDTEAM: RolePersona(
        role=CouncilRole.QA_REDTEAM,
        capability="council.review.qa",
        system_prompt=(
            "Assess falsifiability, edge cases, regression coverage, failure modes, "
            "and acceptance evidence. Raise a formal dispute for material gaps."
        ),
    ),
}


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class CouncilAgenda(BaseModel):
    """Content-addressed work agenda bound to one context packet."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    agenda_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    task_id: str = Field(min_length=1)
    context_packet_id: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    requested_action: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    affected_files: tuple[str, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        context_packet_id: str,
        objective: str,
        requested_action: str,
        resource: str,
        affected_files: tuple[str, ...] | list[str] = (),
    ) -> CouncilAgenda:
        values = {
            "task_id": task_id,
            "context_packet_id": context_packet_id,
            "objective": objective,
            "requested_action": requested_action,
            "resource": resource,
        }
        if any(
            not isinstance(value, str) or not value.strip() for value in values.values()
        ):
            raise ValueError("council agenda text fields must be non-empty strings")
        raw_files = tuple(affected_files)
        if any(not isinstance(path, str) or not path.strip() for path in raw_files):
            raise ValueError("affected_files must contain non-empty paths")
        values = {key: value.strip() for key, value in values.items()}
        files = tuple(sorted({path.strip() for path in raw_files}))
        identity = {
            **values,
            "affected_files": files,
        }
        return cls(agenda_id=_digest(identity), **identity)

    @model_validator(mode="after")
    def validate_identity(self) -> CouncilAgenda:
        text_values = (
            self.task_id,
            self.context_packet_id,
            self.objective,
            self.requested_action,
            self.resource,
            *self.affected_files,
        )
        if any(not value.strip() or value != value.strip() for value in text_values):
            raise ValueError("council agenda values must be canonical non-empty text")
        if self.affected_files != tuple(sorted(set(self.affected_files))):
            raise ValueError("affected_files must be unique and sorted")
        expected = _digest(
            {
                "task_id": self.task_id,
                "context_packet_id": self.context_packet_id,
                "objective": self.objective,
                "requested_action": self.requested_action,
                "resource": self.resource,
                "affected_files": self.affected_files,
            }
        )
        if self.agenda_id != expected:
            raise ValueError("council agenda digest is invalid")
        return self


class CouncilDisputeProposal(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str = Field(min_length=1)


class CouncilDisputeResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    dispute_id: str = Field(min_length=1)
    evidence: Evidence
    resolution_note: str = Field(min_length=1)


class CouncilTurnRouteBinding(BaseModel):
    """Complete frozen assignment/provider identity included in a turn digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assignment_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    route_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    connection_id: str = Field(min_length=1)
    connection_version: int = Field(ge=1)
    deployment_id: str = Field(min_length=1)
    deployment_revision: int = Field(ge=1)
    model_id: str = Field(min_length=1)
    model_family: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    role: CouncilRole
    protocol_function: ProtocolFunction
    agent_identity: str = Field(min_length=1)


class CouncilTurnRequest(BaseModel):
    """One content-bound, retry-safe provider request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    turn_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    round_number: int = Field(ge=1)
    turn_kind: CouncilTurnKind
    role: CouncilRole
    agent_identity: str = Field(min_length=1)
    persona: RolePersona
    binding: CouncilSessionBinding
    agenda: CouncilAgenda
    hypothesis: Hypothesis
    route: CouncilTurnRouteBinding | None = None
    open_disputes: tuple[Dispute, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        provider_id: str,
        session_id: str,
        round_number: int,
        turn_kind: CouncilTurnKind,
        role: CouncilRole,
        agent_identity: str,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
        hypothesis: Hypothesis,
        route: CouncilTurnRouteBinding | None = None,
        open_disputes: tuple[Dispute, ...] = (),
    ) -> CouncilTurnRequest:
        identity = cls._identity(
            provider_id=provider_id,
            session_id=session_id,
            round_number=round_number,
            turn_kind=turn_kind,
            role=role,
            agent_identity=agent_identity,
            binding=binding,
            agenda=agenda,
            hypothesis=hypothesis,
            route=route,
            open_disputes=open_disputes,
        )
        return cls(
            turn_id=_digest(identity),
            provider_id=provider_id,
            session_id=session_id,
            round_number=round_number,
            turn_kind=turn_kind,
            role=role,
            agent_identity=agent_identity,
            persona=ROLE_PERSONAS[role],
            binding=binding,
            agenda=agenda,
            hypothesis=hypothesis.model_copy(deep=True),
            route=route,
            open_disputes=tuple(d.model_copy(deep=True) for d in open_disputes),
        )

    @staticmethod
    def _identity(
        *,
        provider_id: str,
        session_id: str,
        round_number: int,
        turn_kind: CouncilTurnKind,
        role: CouncilRole,
        agent_identity: str,
        binding: CouncilSessionBinding,
        agenda: CouncilAgenda,
        hypothesis: Hypothesis,
        route: CouncilTurnRouteBinding | None,
        open_disputes: tuple[Dispute, ...],
    ) -> dict[str, Any]:
        return {
            "provider_id": provider_id,
            "session_id": session_id,
            "round_number": round_number,
            "turn_kind": turn_kind.value,
            "role": role.value,
            "agent_identity": agent_identity,
            "binding": binding.model_dump(mode="json"),
            "agenda_id": agenda.agenda_id,
            "hypothesis": hypothesis.model_dump(
                mode="json",
                exclude={"updated_at"},
            ),
            "route": None if route is None else route.model_dump(mode="json"),
            "open_disputes": [
                {
                    "dispute_id": dispute.dispute_id,
                    "hypothesis_id": dispute.hypothesis_id,
                    "raised_by_agent_id": dispute.raised_by_agent_id,
                    "reason": dispute.reason,
                    "status": dispute.status.value,
                }
                for dispute in sorted(open_disputes, key=lambda item: item.dispute_id)
            ],
        }

    @model_validator(mode="after")
    def validate_identity(self) -> CouncilTurnRequest:
        if self.persona != ROLE_PERSONAS[self.role]:
            raise ValueError("turn persona does not match the assigned role")
        if self.route is not None and (
            self.route.role is not self.role
            or self.route.agent_identity != self.agent_identity
            or self.provider_id != self.route.connection_id
        ):
            raise ValueError("turn route does not match role, agent, and provider")
        expected = _digest(
            self._identity(
                provider_id=self.provider_id,
                session_id=self.session_id,
                round_number=self.round_number,
                turn_kind=self.turn_kind,
                role=self.role,
                agent_identity=self.agent_identity,
                binding=self.binding,
                agenda=self.agenda,
                hypothesis=self.hypothesis,
                route=self.route,
                open_disputes=self.open_disputes,
            )
        )
        if self.turn_id != expected:
            raise ValueError("council turn digest is invalid")
        return self


class CouncilTurnDecision(BaseModel):
    """Provider-neutral decision before request binding is attached."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assessment: str = Field(min_length=1)
    approved: bool | None = None
    evidence: tuple[Evidence, ...] = ()
    disputes: tuple[CouncilDisputeProposal, ...] = ()
    resolutions: tuple[CouncilDisputeResolution, ...] = ()


class CouncilTurnResponse(CouncilTurnDecision):
    """Provider output cryptographically bound to the exact requested turn."""

    turn_id: str = Field(min_length=1)
    agent_identity: str = Field(min_length=1)
    role: CouncilRole


class CouncilRoleAssignment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: CouncilRole
    agent_identity: str = Field(min_length=1)
    capability: str = Field(min_length=1)
