"""Decision lifecycle and authority gate service."""
from __future__ import annotations

from datetime import datetime, timezone
from threading import RLock
from typing import Iterable, Optional

from domain.decision import AgentVote, Decision, DecisionStatus, HumanDecision, RiskLevel
from domain.human_control_policy import HumanControlPolicy
from phase4.authority.engine import AuthorityEngine, AuthorityError
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest


class DecisionNotFoundError(LookupError):
    pass


class DecisionGateError(ValueError):
    pass


class DecisionGateService:
    """Owns decision lifecycle without granting authority outside AI-3."""

    def __init__(
        self,
        *,
        policy: Optional[HumanControlPolicy] = None,
        authority_engine: Optional[AuthorityEngine] = None,
    ) -> None:
        self._policy = policy or HumanControlPolicy()
        self._authority_engine = authority_engine
        self._decisions: dict[str, Decision] = {}
        self._lock = RLock()

    @property
    def policy(self) -> HumanControlPolicy:
        return self._policy

    def create(self, decision: Decision) -> Decision:
        with self._lock:
            if decision.decision_id in self._decisions:
                raise DecisionGateError("decision_id already exists")
            gate = self._policy.gate_status(
                risk_level=decision.risk_level,
                category=decision.category,
            )
            if gate == "HUMAN_REQUIRED":
                decision.status = DecisionStatus.HUMAN_REQUIRED
            elif self._policy.evaluate(
                risk_level=decision.risk_level,
                category=decision.category,
            ) == "AUTONOMOUS":
                decision.status = DecisionStatus.APPROVED
                decision.human_decision = HumanDecision(
                    selected_alternative=decision.alternatives[0].key,
                    rationale="Automatically approved by LOW-risk human control policy.",
                    decided_by="system:human-control-policy",
                )
                decision.resolved_at = datetime.now(timezone.utc)
            else:
                decision.status = DecisionStatus.PROPOSED
            self._decisions[decision.decision_id] = decision
            return decision.model_copy(deep=True)

    def pending(self, *, project_id: Optional[str] = None) -> list[Decision]:
        with self._lock:
            values = self._decisions.values()
            if project_id is not None:
                values = (item for item in values if item.project_id == project_id)
            return [
                item.model_copy(deep=True)
                for item in values
                if item.status in {DecisionStatus.PROPOSED, DecisionStatus.HUMAN_REQUIRED}
            ]

    def get(self, decision_id: str) -> Decision:
        with self._lock:
            try:
                return self._decisions[decision_id].model_copy(deep=True)
            except KeyError as exc:
                raise DecisionNotFoundError(decision_id) from exc

    def resolve_human(
        self,
        decision_id: str,
        *,
        selected_alternative: str,
        rationale: str,
        decided_by: str,
    ) -> Decision:
        with self._lock:
            decision = self._get_mutable(decision_id)
            decision.resolve(
                HumanDecision(
                    selected_alternative=selected_alternative,
                    rationale=rationale,
                    decided_by=decided_by,
                )
            )
            return decision.model_copy(deep=True)

    def resolve_by_council(
        self,
        decision_id: str,
        votes: Iterable[AgentVote],
    ) -> Decision:
        """Resolve MEDIUM-risk decisions only when every supplied vote agrees."""
        with self._lock:
            decision = self._get_mutable(decision_id)
            vote_list = list(votes)
            if not vote_list:
                raise DecisionGateError("council requires at least one vote")
            selected = {vote.selected_alternative.upper() for vote in vote_list}
            if len(selected) != 1:
                raise DecisionGateError("council is not unanimous")
            if decision.risk_level is not RiskLevel.MEDIUM:
                raise DecisionGateError("council auto-resolution is only permitted for MEDIUM risk")
            decision.agent_votes = vote_list
            decision.resolve(
                HumanDecision(
                    selected_alternative=selected.pop(),
                    rationale="Unanimous AI council recommendation under MEDIUM-risk policy.",
                    decided_by="system:agent-council",
                )
            )
            return decision.model_copy(deep=True)

    def issue_authority_grant(
        self,
        decision_id: str,
        *,
        agent_identity: str,
        action: str,
        resource: str,
        context_packet_id: str,
        capability: Optional[str] = None,
    ) -> VerifiedAuthorityGrant:
        """Issue AI-3 authority only after an explicit approved decision gate."""
        decision = self.get(decision_id)
        if decision.status is not DecisionStatus.APPROVED:
            raise DecisionGateError("required decision is not APPROVED")
        if self._authority_engine is None:
            raise DecisionGateError("authority engine is not configured")
        request = AuthorityRequest.create(
            agent_identity=agent_identity,
            action=action,
            resource=resource,
            context_packet_id=context_packet_id,
            capability=capability,
            context={
                "decision_id": decision.decision_id,
                "project_id": decision.project_id,
                "decision_status": decision.status.value,
            },
        )
        try:
            return self._authority_engine.issue_grant(request)
        except AuthorityError as exc:
            raise DecisionGateError(str(exc)) from exc

    def _get_mutable(self, decision_id: str) -> Decision:
        try:
            return self._decisions[decision_id]
        except KeyError as exc:
            raise DecisionNotFoundError(decision_id) from exc
