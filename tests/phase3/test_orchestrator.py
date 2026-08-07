from __future__ import annotations

import pytest

from domain.distribution import DispatchRecord
from domain.orchestration import (
    OrchestrationError,
    OrchestrationRequest,
    OrchestrationSnapshot,
    OrchestrationState,
    RetryPolicy,
)
from domain.verification import DeliveredProduct, VerificationCheck, VerificationResult
from services.orchestrator import Orchestrator


class FakeExecution:
    def __init__(self, statuses: list[str]) -> None:
        self.statuses = iter(statuses)
        self.calls = 0

    def execute(self, dispatch, product, *, cwd, adapters):
        self.calls += 1
        status = next(self.statuses)
        failures = () if status == "PASS" else ("verification failure",)
        result = VerificationResult(
            verification_id=f"verification-{self.calls}",
            status=status,
            package_fingerprint=dispatch.package_fingerprint,
            contract_fingerprint=dispatch.contract_fingerprint,
            dispatch_fingerprint=dispatch.fingerprint,
            artifact_fingerprint=product.artifact_fingerprint,
            checks=(VerificationCheck(f"check-{self.calls}", status == "PASS", status),),
            evidence_ids=(),
            failures=failures,
        )
        return product, result


def dispatch() -> DispatchRecord:
    return DispatchRecord(
        schema_version="0.1",
        dispatch_id="dispatch-1",
        task_id="task-1",
        task_fingerprint="task-fp",
        package_id="package-1",
        package_fingerprint="package-fp",
        selected_role="tester",
        contract_id="contract-1",
        contract_fingerprint="contract-fp",
        required_inputs=("source",),
        permitted_outputs=("report",),
    )


def product() -> DeliveredProduct:
    return DeliveredProduct("artifact-1", "artifact-fp", ("report",), ())


def request(policy: RetryPolicy | None = None) -> OrchestrationRequest:
    return OrchestrationRequest(
        task_id="task-1",
        task_fingerprint="task-fp",
        package_id="package-1",
        package_fingerprint="package-fp",
        available_inputs=("source",),
        selected_role="tester",
        policy=policy or RetryPolicy(),
    )


def test_happy_path_preserves_authority_and_fingerprints(tmp_path):
    execution = FakeExecution(["PASS"])
    outcome = Orchestrator(execution).run(
        request(), dispatch=dispatch(), product=product(), cwd=tmp_path, adapters=(object(),)
    )
    assert outcome.result.final_state is OrchestrationState.COMPLETED
    assert outcome.result.attempt == 1
    assert outcome.result.dispatch_fingerprint == dispatch().fingerprint
    assert outcome.result.artifact_fingerprint == "artifact-fp"
    assert outcome.verification is not None
    assert outcome.verification.status == "PASS"
    assert execution.calls == 1


def test_verification_fail_is_not_rewritten_as_pass(tmp_path):
    execution = FakeExecution(["FAIL"])
    outcome = Orchestrator(execution).run(
        request(), dispatch=dispatch(), product=product(), cwd=tmp_path, adapters=(object(),)
    )
    assert outcome.result.final_state is OrchestrationState.FAILED
    assert outcome.result.failure_reason == "VERIFICATION_FAIL"
    assert outcome.verification is not None and outcome.verification.status == "FAIL"


def test_bounded_retry_runs_a_new_evidence_cycle(tmp_path):
    execution = FakeExecution(["FAIL", "PASS"])
    policy = RetryPolicy("retry-on-verification", max_attempts=2, retryable_failures=("VERIFICATION_FAIL",))
    outcome = Orchestrator(execution).run(
        request(policy), dispatch=dispatch(), product=product(), cwd=tmp_path, adapters=(object(),)
    )
    assert outcome.result.final_state is OrchestrationState.COMPLETED
    assert outcome.result.attempt == 2
    assert execution.calls == 2
    assert outcome.verification is not None and outcome.verification.status == "PASS"


def test_retry_budget_exhaustion_escalates(tmp_path):
    execution = FakeExecution(["FAIL", "FAIL"])
    policy = RetryPolicy("retry-on-verification", max_attempts=2, retryable_failures=("VERIFICATION_FAIL",))
    outcome = Orchestrator(execution).run(
        request(policy), dispatch=dispatch(), product=product(), cwd=tmp_path, adapters=(object(),)
    )
    assert outcome.result.final_state is OrchestrationState.ESCALATED
    assert outcome.result.failure_reason == "POLICY_EXHAUSTED"
    assert outcome.result.attempt == 2


def test_invalid_state_transition_is_rejected():
    snapshot = OrchestrationSnapshot("orch-1", OrchestrationState.RECEIVED)
    with pytest.raises(OrchestrationError):
        snapshot.transition(OrchestrationState.COMPLETED)


def test_orchestration_identity_is_deterministic():
    assert request().orchestration_id == request().orchestration_id


def test_dispatch_mismatch_is_rejected(tmp_path):
    bad = DispatchRecord(
        schema_version="0.1", dispatch_id="dispatch-1", task_id="wrong", task_fingerprint="task-fp",
        package_id="package-1", package_fingerprint="package-fp", selected_role="tester",
        contract_id="contract-1", contract_fingerprint="contract-fp", required_inputs=("source",),
        permitted_outputs=("report",),
    )
    with pytest.raises(OrchestrationError):
        Orchestrator(FakeExecution(["PASS"])).run(
            request(), dispatch=bad, product=product(), cwd=tmp_path, adapters=(object(),)
        )
