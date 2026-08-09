"""P5-01 execution boundary tests."""

from __future__ import annotations

from datetime import datetime, timezone
import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from execution import ExecutionEngine, ExecutionError  # noqa: E402
from p5_00_loader import load_contract_api  # noqa: E402

api = load_contract_api()


def make_contract():
    return api.AIWorkProductContract(
        contract_id="p5-01-test",
        contract_version="1.0",
        product_type="test-product",
        product_location="tests/output",
        intent="prove execution boundary",
        inputs=("input",),
        required_artifacts=(api.ArtifactRequirement(
            artifact_id="result",
            artifact_type=api.ArtifactType.FILE,
            location="tests/output/result.txt",
        ),),
        outputs=("result",),
        acceptance_criteria=(api.AcceptanceCriterion(
            criterion_id="criterion-1",
            requirement="result exists",
            predicate="exists",
            verifier="p3-20",
            evidence_source="test-runtime",
        ),),
        verification_procedure=api.VerificationProcedure(
            procedure_id="p3-20-test",
            verifier="p3-20",
            method="governed-test",
            version="1",
        ),
        regression_requirements=(),
        required_capabilities=(),
        authority_boundaries=("agent cannot decide verification",),
        forbidden_actions=("self-approve",),
        forbidden_outputs=("authoritative-pass",),
    )


def make_submission(contract, execution_id="exec-1", agent_id="agent-1"):
    return api.WorkProductSubmission(
        submission_id=execution_id,
        contract_fingerprint=contract.contract_fingerprint,
        agent_id=agent_id,
        repository_state=api.RepositoryState(
            repository="smoeberg/kodegenerator",
            revision="test-revision",
            tree_fingerprint="tree-fingerprint",
            clean=True,
        ),
        artifacts=(),
        candidate_evidence=(),
        submitted_at=datetime.now(timezone.utc),
    )


class Executor:
    def __init__(self, submission_factory):
        self.submission_factory = submission_factory

    def execute(self, context):
        return self.submission_factory(context)


def test_execution_stops_at_submitted():
    contract = make_contract()
    result = ExecutionEngine().execute(
        contract,
        "agent-1",
        Executor(lambda ctx: make_submission(ctx.contract, ctx.execution_id, ctx.agent_id)),
        execution_id="exec-1",
    )
    assert result.state is api.DeliveryState.SUBMITTED
    assert [event.event_type for event in result.events] == [
        api.DeliveryState.DISPATCHED,
        api.DeliveryState.IN_PROGRESS,
        api.DeliveryState.SUBMITTED,
    ]
    assert all(event.actor_role is not api.ActorRole.P3_20 for event in result.events)


def test_execution_rejects_contract_mismatch():
    contract = make_contract()
    other = make_contract()
    object.__setattr__(other, "contract_fingerprint", "different")
    try:
        ExecutionEngine().execute(
            contract,
            "agent-1",
            Executor(lambda ctx: make_submission(other, ctx.execution_id, ctx.agent_id)),
            execution_id="exec-2",
        )
    except ExecutionError as exc:
        assert "contract fingerprint" in str(exc)
    else:
        raise AssertionError("expected ExecutionError")


def test_execution_rejects_wrong_agent_identity():
    contract = make_contract()
    try:
        ExecutionEngine().execute(
            contract,
            "agent-1",
            Executor(lambda ctx: make_submission(ctx.contract, ctx.execution_id, "other-agent")),
            execution_id="exec-3",
        )
    except ExecutionError as exc:
        assert "agent_id" in str(exc)
    else:
        raise AssertionError("expected ExecutionError")
