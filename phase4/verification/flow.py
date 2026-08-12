"""First deterministic end-to-end Brain verification slice."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from phase4.agent_registry import AgentRegistry, AgentRole
from phase4.contracts import KnowledgeRecord, KnowledgeState, VerificationMode, VerificationPolicy

from .case import VerificationCase
from .engine import VerificationEngine, VerificationResult
from .selector import VerifierSelector


class KnowledgeAppender(Protocol):
    def append_and_materialize(self, record: KnowledgeRecord) -> int: ...


@dataclass(frozen=True)
class BrainVerificationOutcome:
    record: KnowledgeRecord
    result: VerificationResult
    selected_agent_ids: tuple[str, ...]
    materialized_version: int | None


class BrainVerificationFlow:
    """Compose selection, case lifecycle, evaluation, and Brain materialization.

    This is deliberately a small vertical slice. It owns no LLM calls,
    worker scheduling, LibreChat integration, or execution authority.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        store: KnowledgeAppender,
        *,
        selector: VerifierSelector | None = None,
        engine: VerificationEngine | None = None,
    ) -> None:
        self._selector = selector or VerifierSelector(registry)
        self._engine = engine or VerificationEngine()
        self._store = store

    def verify_quorum(
        self,
        record: KnowledgeRecord,
        policy: VerificationPolicy,
        *,
        role: AgentRole | None = None,
        capability: str | None = None,
        observations: dict[str, bool],
    ) -> BrainVerificationOutcome:
        if policy.mode is not VerificationMode.QUORUM:
            raise ValueError("verify_quorum requires quorum verification policy")

        selection = self._selector.select(
            claim_id=record.record_id,
            policy_id=self._policy_id(policy),
            quorum_size=policy.quorum_size,
            role=role,
            capability=capability,
        )
        case = VerificationCase(record.record_id, self._policy_id(policy), selection)
        for agent_id, outcome in observations.items():
            case.record(agent_id, outcome)

        result = self._engine.evaluate(policy, case.observations.values())
        if result is VerificationResult.INSUFFICIENT:
            return BrainVerificationOutcome(
                record=record,
                result=result,
                selected_agent_ids=selection.selected_ids,
                materialized_version=None,
            )

        case.complete(result)
        state = {
            VerificationResult.CONFIRMED: KnowledgeState.CONFIRMED,
            VerificationResult.DISPUTED: KnowledgeState.DISPUTED,
        }.get(result)
        materialized_version = None
        materialized_record = record
        if state is not None:
            materialized_record = KnowledgeRecord(
                record_id=record.record_id,
                subject=record.subject,
                claim=record.claim,
                evidence=record.evidence,
                state=state,
                version=record.version,
                author_agent_id=record.author_agent_id,
            )
            materialized_version = self._store.append_and_materialize(materialized_record)

        return BrainVerificationOutcome(
            record=materialized_record,
            result=result,
            selected_agent_ids=selection.selected_ids,
            materialized_version=materialized_version,
        )

    @staticmethod
    def _policy_id(policy: VerificationPolicy) -> str:
        return f"verification:{policy.mode.value}:{policy.quorum_size}:{policy.risk_level}"
