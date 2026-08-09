from datetime import datetime, timezone

import pytest

from phase5.p5_00_ai_work_product_contract import (
    ActorRole, ArtifactRequirement, ArtifactType, CandidateEvidence, DeliveryState,
    LifecycleEvent, RepositoryState, SubmittedArtifact, WorkProductSubmission,
    append_event, derive_delivery_state, EvidenceAuthority, VerificationEngine,
    VerificationError, fingerprint,
)
from phase5.p5_00_ai_work_product_contract.tests.test_contract import make_contract


def event(event_id, submission, kind, actor, contract_fp="contract-fp", role=ActorRole.AGENT):
    return LifecycleEvent(event_id, submission, kind, actor, datetime.now(timezone.utc), contract_fp, role)


def make_submission(contract):
    return WorkProductSubmission(
        submission_id="sub-1",
        contract_fingerprint=contract.contract_fingerprint,
        agent_id="agent-1",
        repository_state=RepositoryState("smoeberg/kodegenerator", "abc123", "tree123", True),
        artifacts=(SubmittedArtifact("domain", ArtifactType.FILE, "models.py", "artifact123"),),
        candidate_evidence=(CandidateEvidence("ev-1", "P5-00-AC-001", "agent", fingerprint({"pass": True})),),
        submitted_at=datetime.now(timezone.utc),
    )


def test_agent_cannot_enter_verifying_or_issue_pass():
    events = ()
    events = append_event(events, event("1", "sub-1", DeliveryState.DISPATCHED, "dor-runtime", role=ActorRole.RUNTIME))
    events = append_event(events, event("2", "sub-1", DeliveryState.IN_PROGRESS, "agent-1"))
    events = append_event(events, event("3", "sub-1", DeliveryState.SUBMITTED, "agent-1"))
    with pytest.raises(PermissionError):
        append_event(events, event("4", "sub-1", DeliveryState.VERIFYING, "agent-1"))


def test_verification_runtime_can_start_and_p3_20_can_resolve():
    events = ()
    for number, kind in enumerate((DeliveryState.DISPATCHED, DeliveryState.IN_PROGRESS, DeliveryState.SUBMITTED), 1):
        role = ActorRole.RUNTIME if kind is DeliveryState.DISPATCHED else ActorRole.AGENT
        actor = "dor-runtime" if role is ActorRole.RUNTIME else "agent-1"
        events = append_event(events, event(str(number), "sub-1", kind, actor, role=role))
    events = append_event(events, event("4", "sub-1", DeliveryState.VERIFYING, "verification-runtime", role=ActorRole.VERIFICATION_RUNTIME))
    events = append_event(events, event("5", "sub-1", DeliveryState.FAILED, "p3-20", role=ActorRole.P3_20))
    assert derive_delivery_state(events) is DeliveryState.FAILED


def test_terminal_failed_submission_cannot_be_rewritten():
    events = ()
    for number, kind, actor, role in (
        ("1", DeliveryState.DISPATCHED, "dor-runtime", ActorRole.RUNTIME),
        ("2", DeliveryState.IN_PROGRESS, "agent", ActorRole.AGENT),
        ("3", DeliveryState.SUBMITTED, "agent", ActorRole.AGENT),
        ("4", DeliveryState.VERIFYING, "verification-runtime", ActorRole.VERIFICATION_RUNTIME),
        ("5", DeliveryState.FAILED, "p3-20", ActorRole.P3_20),
    ):
        events = append_event(events, event(number, "sub-1", kind, actor, role=role))
    with pytest.raises(ValueError):
        append_event(events, event("6", "sub-1", DeliveryState.VERIFYING, "verification-runtime", role=ActorRole.VERIFICATION_RUNTIME))


def test_missing_required_artifact_fails_closed():
    contract = make_contract()
    submission = WorkProductSubmission(
        submission_id="sub-2", contract_fingerprint=contract.contract_fingerprint, agent_id="agent",
        repository_state=RepositoryState("repo", "rev", "tree", True), artifacts=(), candidate_evidence=(),
        submitted_at=datetime.now(timezone.utc),
    )
    decision = VerificationEngine().verify(contract, submission, (), {}, decision_id="dec-1", actual_repository_state=submission.repository_state)
    assert decision.passed is False


def test_candidate_evidence_is_not_governed_evidence():
    with pytest.raises(ValueError):
        CandidateEvidence("x", "c", "agent", "fp", authority=EvidenceAuthority.GOVERNED)


def test_contract_mismatch_fails_closed():
    contract = make_contract()
    submission = make_submission(contract)
    bad = WorkProductSubmission(
        submission_id=submission.submission_id, contract_fingerprint="wrong", agent_id=submission.agent_id,
        repository_state=submission.repository_state, artifacts=submission.artifacts,
        candidate_evidence=submission.candidate_evidence, submitted_at=submission.submitted_at,
    )
    with pytest.raises(VerificationError):
        VerificationEngine().verify(contract, bad, (), {}, decision_id="dec-2", actual_repository_state=submission.repository_state)


def test_lifecycle_contract_fingerprint_is_immutable():
    events = append_event((), event("1", "sub-1", DeliveryState.DISPATCHED, "dor-runtime", "fp-a", ActorRole.RUNTIME))
    with pytest.raises(ValueError):
        append_event(events, event("2", "sub-1", DeliveryState.IN_PROGRESS, "agent-1", "fp-b", ActorRole.AGENT))
