"""Contract tests for Phase 4 AI-5 outcome/state-transition boundary."""

from dataclasses import FrozenInstanceError, replace

import pytest

from phase4.execution.models import ExecutionResult, ExecutionStatus


class TestAI5OutcomeContract:
    def test_success_produces_outcome(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        outcome = _process(result)
        assert outcome.status.value == "succeeded"
        assert outcome.execution_id == result.execution_id

    def test_failed_execution_produces_failed_outcome(self):
        result = _result(ExecutionStatus.FAILED)
        outcome = _process(result)
        assert outcome.status.value == "failed"

    def test_unknown_execution_is_not_failed(self):
        result = _result(ExecutionStatus.FAILED)
        result = replace(result, error="result unknown after external timeout")
        outcome = _process(result, force_unknown=True)
        assert outcome.status.value == "unknown"
        assert outcome.status.value != "failed"

    def test_outcome_identity_is_deterministic(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        first = _process(result)
        second = _process(result)
        assert first.outcome_id == second.outcome_id

    def test_replayed_execution_is_idempotent(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        first = _process(result)
        second = _process(result)
        assert first.outcome_id == second.outcome_id
        assert first.transitions == second.transitions

    def test_duplicate_outcome_does_not_repeat_transition(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        first = _process(result, transition=("pending", "confirmed"))
        second = _process(result, transition=("pending", "confirmed"))
        assert first.transitions == second.transitions
        assert len(second.transitions) <= 1

    def test_invalid_transition_fails_closed(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        with pytest.raises(ValueError):
            _process(result, transition=("pending", "unknown"))

    def test_unknown_state_fails_closed(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        with pytest.raises(ValueError):
            _process(result, transition=("does-not-exist", "confirmed"))

    def test_execution_result_is_immutable(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        with pytest.raises(FrozenInstanceError):
            result.status = ExecutionStatus.FAILED

    def test_provenance_binds_outcome_to_execution(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        outcome = _process(result)
        assert outcome.execution_id == result.execution_id
        assert outcome.request_id == result.request_id
        assert outcome.provenance_id

    def test_outcome_cannot_execute_side_effects(self):
        result = _result(ExecutionStatus.SUCCEEDED)
        outcome = _process(result)
        assert not hasattr(outcome, "execute")
        assert not hasattr(outcome, "adapter")


def _result(status: ExecutionStatus) -> ExecutionResult:
    return ExecutionResult(
        execution_id="exec-001",
        request_id="req-001",
        authority_policy_id="policy-001",
        authority_policy_version="1",
        agent_identity="agent-001",
        action="confirm",
        resource="order:001",
        context_packet_id="ctx-001",
        status=status,
        adapter_id="adapter-001",
        output=(("result", "ok"),),
        error=None,
        executed_at="2026-08-08T12:00:00Z",
    )


def _process(result, *, transition=None, force_unknown=False):
    """Placeholder: implementation is intentionally absent in contract phase."""
    raise NotImplementedError("AI-5 contract implementation pending")
