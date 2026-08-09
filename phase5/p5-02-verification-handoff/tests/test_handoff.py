"""Core P5-02 handoff tests."""

from datetime import datetime, timezone
import sys
from pathlib import Path

SLICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SLICE))

from handoff import HandoffTransportError, VerificationHandoffEngine  # noqa: E402
from models import HandoffError, HandoffState  # noqa: E402
from p5_00_loader import load_p5_00  # noqa: E402

p5 = load_p5_00()


def fixture():
    contract = p5.AIWorkProductContract(
        contract_id="p5-02-test",
        contract_version="1",
        product_type="test",
        product_location="tests/output",
        intent="test handoff",
        inputs=("input",),
        required_artifacts=(p5.ArtifactRequirement("result", p5.ArtifactType.FILE, "tests/output/result.txt"),),
        outputs=("result",),
        acceptance_criteria=(p5.AcceptanceCriterion("criterion-1", "result is valid", "predicate", "p3-20", "test"),),
        verification_procedure=p5.VerificationProcedure("verify-1", "p3-20", "governed", "1"),
        regression_requirements=(), required_capabilities=(),
        authority_boundaries=("P5-02 cannot decide",),
        forbidden_actions=("self-approve",), forbidden_outputs=("verification-decision",),
    )
    submission = p5.WorkProductSubmission(
        submission_id="submission-1",
        contract_fingerprint=contract.contract_fingerprint,
        agent_id="agent-1",
        repository_state=p5.RepositoryState("repo", "revision", "tree", True),
        artifacts=(),
        candidate_evidence=(p5.CandidateEvidence("candidate-1", "criterion-1", "test", "candidate-fp"),),
        submitted_at=datetime.now(timezone.utc),
    )
    events = ()
    for state, actor, role in (
        (p5.DeliveryState.DISPATCHED, "runtime", p5.ActorRole.RUNTIME),
        (p5.DeliveryState.IN_PROGRESS, "agent-1", p5.ActorRole.AGENT),
        (p5.DeliveryState.SUBMITTED, "agent-1", p5.ActorRole.AGENT),
    ):
        events = p5.append_event(events, p5.LifecycleEvent(
            event_id=f"event-{state.value}", submission_id=submission.submission_id,
            event_type=state, actor_id=actor, actor_role=role,
            contract_fingerprint=contract.contract_fingerprint,
            occurred_at=datetime.now(timezone.utc),
        ))
    return contract, submission, events


def decision(contract, submission, passed=True):
    return p5.VerificationDecision(
        decision_id="decision-1",
        submission_id=submission.submission_id,
        submission_fingerprint=submission.submission_fingerprint,
        contract_fingerprint=contract.contract_fingerprint,
        verifier="p3-20",
        passed=passed,
        criterion_results=(p5.CriterionResult("criterion-1", passed, ("governed-1",), "p3-20", "test"),),
        decided_at=datetime.now(timezone.utc),
    )


def test_prepare_requires_submitted_state():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    with_invalid = events[:-1]
    try:
        engine.prepare(contract, submission, lifecycle_events=with_invalid)
    except HandoffError as exc:
        assert "SUBMITTED" in str(exc)
    else:
        raise AssertionError("expected SUBMITTED gate")


def test_prepare_is_idempotent_for_same_immutable_subject():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    first = engine.prepare(contract, submission, lifecycle_events=events, request_id="request-a")
    second = engine.prepare(contract, submission, lifecycle_events=events, request_id="request-b")
    assert first is second
    assert first.request_fingerprint == second.request_fingerprint


def test_dispatch_binds_only_matching_p3_20_decision():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    request = engine.prepare(contract, submission, lifecycle_events=events)
    result = engine.dispatch(request, lambda _: decision(contract, submission, True))
    assert result.state is HandoffState.VERIFIED_PASSED
    assert [e.state for e in engine.events(request)] == [
        HandoffState.VERIFICATION_READY,
        HandoffState.VERIFICATION_DISPATCHED,
        HandoffState.VERIFICATION_RETURNED,
        HandoffState.VERIFIED_PASSED,
    ]
    assert result.request.submission.candidate_evidence[0].authority is p5.EvidenceAuthority.CANDIDATE


def test_wrong_verifier_is_rejected():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    request = engine.prepare(contract, submission, lifecycle_events=events)
    bad = decision(contract, submission)
    object.__setattr__(bad, "verifier", "other-verifier")
    try:
        engine.bind_response(request, p5.VerificationResponse(bad, datetime.now(timezone.utc)))
    except HandoffError as exc:
        assert "p3-20" in str(exc)
    else:
        raise AssertionError("expected verifier rejection")


def test_mismatched_submission_is_rejected():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    request = engine.prepare(contract, submission, lifecycle_events=events)
    bad = decision(contract, submission)
    object.__setattr__(bad, "submission_id", "different-submission")
    try:
        engine.bind_response(request, p5.VerificationResponse(bad, datetime.now(timezone.utc)))
    except HandoffError as exc:
        assert "submission mismatch" in str(exc)
    else:
        raise AssertionError("expected submission rejection")


def test_transport_failure_is_not_verification_failure():
    contract, submission, events = fixture()
    engine = VerificationHandoffEngine()
    request = engine.prepare(contract, submission, lifecycle_events=events)
    try:
        engine.dispatch(request, lambda _: (_ for _ in ()).throw(HandoffTransportError("offline")))
    except HandoffError as exc:
        assert "transport failed" in str(exc)
    else:
        raise AssertionError("expected transport failure")
    states = [e.state for e in engine.events(request)]
    assert states[-1] is HandoffState.VERIFICATION_REJECTED
    assert HandoffState.VERIFIED_PASSED not in states
    assert HandoffState.VERIFIED_FAILED not in states
