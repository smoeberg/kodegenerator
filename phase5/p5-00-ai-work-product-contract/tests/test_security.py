from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

PACKAGE_DIR = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "p5_00_contract", PACKAGE_DIR / "__init__.py", submodule_search_locations=[str(PACKAGE_DIR)]
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

ActorRole = module.ActorRole
ArtifactRequirement = module.ArtifactRequirement
ArtifactType = module.ArtifactType
CandidateEvidence = module.CandidateEvidence
DeliveryState = module.DeliveryState
LifecycleEvent = module.LifecycleEvent
RepositoryState = module.RepositoryState
SubmittedArtifact = module.SubmittedArtifact
WorkProductSubmission = module.WorkProductSubmission
append_event = module.append_event
derive_delivery_state = module.derive_delivery_state
EvidenceAuthority = module.EvidenceAuthority
VerificationEngine = module.VerificationEngine
VerificationError = module.VerificationError
fingerprint = module.fingerprint


def make_contract():
    return module.AIWorkProductContract(
        contract_id="P5-00",
        contract_version="1.0.0",
        product_type="ai-work-product",
        product_location="phase5/p5-00-ai-work-product-contract",
        intent="Define and verify DOR work products",
        inputs=("architecture",),
        required_artifacts=(ArtifactRequirement("domain", ArtifactType.FILE, "models.py"),),
        outputs=("verified-work-product",),
        acceptance_criteria=(module.AcceptanceCriterion(
            "P5-00-AC-001", "contract immutable", "contract_immutable", "p3-20", "governed_test_execution"
        ),),
        verification_procedure=module.VerificationProcedure("P3-20", "p3-20", "criterion-by-criterion", "1"),
        regression_requirements=("full-suite",),
        required_capabilities=("repository-write",),
        authority_boundaries=("agent-cannot-verify",),
        forbidden_actions=("self-approve",),
        forbidden_outputs=("agent-pass",),
    )


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
