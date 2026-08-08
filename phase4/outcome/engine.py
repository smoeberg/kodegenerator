"""AI-5 outcome processor."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from phase4.execution.models import ExecutionResult
from .models import OutcomeRecord, OutcomeStatus, StateTransition, outcome_id_for, outcome_status_for, provenance_id_for

_ALLOWED_STATES = frozenset(("pending", "confirmed"))


class OutcomeEngine:
    """Idempotent processor for immutable AI-4 execution results."""

    def __init__(self) -> None:
        self._outcomes: Dict[str, OutcomeRecord] = {}

    def process(self, result: ExecutionResult, *, transition: Optional[Tuple[str, str]] = None, force_unknown: bool = False) -> OutcomeRecord:
        status = outcome_status_for(result, unknown=force_unknown)
        transitions = self._validate_transition(result, transition, status)
        outcome_id = outcome_id_for(result, status, transitions)
        existing = self._outcomes.get(outcome_id)
        if existing is not None:
            return existing
        record = OutcomeRecord(
            outcome_id=outcome_id,
            execution_id=result.execution_id,
            request_id=result.request_id,
            status=status,
            transitions=transitions,
            provenance_id=provenance_id_for(result),
            produced_at=result.executed_at,
            error=result.error,
        )
        self._outcomes[outcome_id] = record
        return record

    @staticmethod
    def _validate_transition(result: ExecutionResult, transition: Optional[Tuple[str, str]], status: OutcomeStatus) -> Tuple[StateTransition, ...]:
        if transition is None:
            return ()
        if status is not OutcomeStatus.SUCCEEDED:
            raise ValueError("state transition requires a successful outcome")
        from_state, to_state = transition
        if from_state not in _ALLOWED_STATES:
            raise ValueError("unknown source state")
        if to_state not in _ALLOWED_STATES:
            raise ValueError("unknown target state")
        if (from_state, to_state) != ("pending", "confirmed"):
            raise ValueError("invalid state transition")
        return (StateTransition(result.resource, from_state, to_state),)

    def get(self, outcome_id: str) -> Optional[OutcomeRecord]:
        return self._outcomes.get(outcome_id)
