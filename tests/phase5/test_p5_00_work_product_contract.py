"""Adversarial contract tests for P5-00 work-product verification."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys


PACKAGE_DIR = Path(__file__).parents[2] / "phase5" / "p5-00-ai-work-product-contract"
SPEC = importlib.util.spec_from_file_location(
    "p5_00_contract", PACKAGE_DIR / "__init__.py", submodule_search_locations=[str(PACKAGE_DIR)]
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

A = module.ArtifactRequirement
C = module.AcceptanceCriterion
Contract = module.AIWorkProductContract
AT = module.ArtifactType
RS = module.RepositoryState
SA = module.SubmittedArtifact
CE = module.CandidateEvidence
WP = module.WorkProductSubmission
VP = module.VerificationProcedure
GF = module.GovernedFact
VE = module.VerificationEngine
VErr = module.VerificationError
AR = module.ActorRole


def contract(*, mandatory=True):
    return Contract(
        contract_id="P5-00-TEST", contract_version="1.0.0", product_type="test-product",
        product_location="phase5/p5-00-ai-work-product-contract",
        intent="prove governed work-product acceptance", inputs=("test-input",),
        required_artifacts=(A("impl", AT.FILE, "src/impl.py"),), outputs=("implemented artifact",),
        acceptance_criteria=(C("AC-1", "tests pass", "tests_pass", "p3-20", "pytest", mandatory),),
        verification_procedure=VP("VP-1", "p3-20", "governed-test-execution", "1.0"),
        regression_requirements=("existing suite remains green",), required_capabilities=("repository-read",),
        authority_boundaries=("agent cannot decide PASS",), forbidden_actions=("mutate contract after dispatch",),
        forbidden_outputs=("agent-issued PASS",),
    )


def submission(c, *, artifact_fingerprint="artifact-hash", candidate=True):
    return WP(
        submission_id="SUB-1", contract_fingerprint=c.contract_fingerprint, agent_id="agent-1",
        repository_state=RS("smoeberg/kodegenerator", "abc123", "tree123", True),
        artifacts=(SA("impl", AT.FILE, "src/impl.py", artifact_fingerprint),),
        candidate_evidence=(CE("cand-1", "AC-1", "agent-report", "candidate-hash"),) if candidate else (),
        submitted_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )


def fact():
    return GF("gov-1", "AC-1", {"passed": True}, "pytest", "governed-hash")


def verify(c, s, *, passed=True, actual_repo=None):
    return VE().verify(
        c, s, (fact(),), {"impl": "artifact-hash"}, decision_id="DEC-1",
        actual_repository_state=actual_repo or s.repository_state,
        predicates={"AC-1": lambda facts: passed},
        governed_evidence_fingerprints={"gov-1": "governed-hash"},
        now=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )


def test_positive_path_ends_in_p3_20_decision():
    c = contract(); s = submission(c); d = verify(c, s)
    assert d.passed is True
    assert d.verifier == "p3-20"
    assert d.submission_fingerprint == s.submission_fingerprint


def test_completion_claim_is_not_authoritative():
    c = contract(); assert verify(c, submission(c), passed=False).passed is False


def test_contract_fingerprint_mismatch_fails_closed():
    c = contract(); s = submission(c); object.__setattr__(s, "contract_fingerprint", "tampered")
    try:
        verify(c, s); assert False
    except VErr:
        pass


def test_required_artifact_missing_fails():
    c = contract()
    s = WP("SUB-2", c.contract_fingerprint, "agent-1", RS("smoeberg/kodegenerator", "abc123", "tree123", True), (), (), datetime.now(timezone.utc))
    assert verify(c, s).passed is False


def test_artifact_fingerprint_mismatch_fails():
    c = contract(); assert verify(c, submission(c, artifact_fingerprint="wrong")).passed is False


def test_artifact_metadata_mismatch_fails():
    c = contract()
    s = WP("SUB-3", c.contract_fingerprint, "agent-1", RS("smoeberg/kodegenerator", "abc123", "tree123", True),
           (SA("impl", AT.FILE, "wrong.py", "artifact-hash"),), (), datetime.now(timezone.utc))
    assert verify(c, s).passed is False


def test_candidate_evidence_cannot_become_authoritative():
    c = contract(); d = verify(c, submission(c, candidate=True))
    assert d.passed is True
    assert d.criterion_results[-1].evidence_ids == ("gov-1",)


def test_missing_governed_evidence_fails():
    c = contract(); s = submission(c)
    d = VE().verify(c, s, (), {"impl": "artifact-hash"}, decision_id="DEC-2", actual_repository_state=s.repository_state)
    assert d.passed is False


def test_missing_predicate_fails_closed():
    c = contract(); s = submission(c)
    d = VE().verify(c, s, (fact(),), {"impl": "artifact-hash"}, decision_id="DEC-3",
                    actual_repository_state=s.repository_state,
                    governed_evidence_fingerprints={"gov-1": "governed-hash"})
    assert d.passed is False


def test_changed_governed_evidence_fails_closed():
    c = contract(); s = submission(c)
    try:
        VE().verify(c, s, (fact(),), {"impl": "artifact-hash"}, decision_id="DEC-4",
                    actual_repository_state=s.repository_state,
                    predicates={"AC-1": lambda facts: True},
                    governed_evidence_fingerprints={"gov-1": "changed-hash"})
        assert False
    except VErr:
        pass


def test_changed_repository_state_fails_closed():
    c = contract(); s = submission(c)
    changed = RS(s.repository_state.repository, "new-revision", "new-tree", True)
    try:
        verify(c, s, actual_repo=changed)
        assert False
    except VErr:
        pass


def test_only_p3_20_can_verify():
    try:
        VE("agent-1"); assert False
    except VErr:
        pass


def test_lifecycle_binds_contract_and_verification_runtime_starts_verifying():
    e = module.LifecycleEvent; events = (); fp = "contract-fp"
    events = module.append_event(events, e("0", "SUB-1", module.DeliveryState.DISPATCHED, "dor-runtime", datetime.now(timezone.utc), fp, AR.RUNTIME))
    events = module.append_event(events, e("1", "SUB-1", module.DeliveryState.IN_PROGRESS, "agent-1", datetime.now(timezone.utc), fp, AR.AGENT))
    events = module.append_event(events, e("2", "SUB-1", module.DeliveryState.SUBMITTED, "agent-1", datetime.now(timezone.utc), fp, AR.AGENT))
    try:
        module.append_event(events, e("3", "SUB-1", module.DeliveryState.VERIFYING, "agent-1", datetime.now(timezone.utc), fp, AR.AGENT)); assert False
    except PermissionError:
        pass
    events = module.append_event(events, e("3", "SUB-1", module.DeliveryState.VERIFYING, "verification-runtime", datetime.now(timezone.utc), fp, AR.VERIFICATION_RUNTIME))
    events = module.append_event(events, e("4", "SUB-1", module.DeliveryState.PASSED, "p3-20", datetime.now(timezone.utc), fp, AR.P3_20))
    assert module.derive_delivery_state(events) is module.DeliveryState.PASSED


def test_lifecycle_rejects_contract_fingerprint_change():
    e = module.LifecycleEvent; events = ()
    events = module.append_event(events, e("0", "SUB-1", module.DeliveryState.DISPATCHED, "dor-runtime", datetime.now(timezone.utc), "fp-a", AR.RUNTIME))
    try:
        module.append_event(events, e("1", "SUB-1", module.DeliveryState.IN_PROGRESS, "agent-1", datetime.now(timezone.utc), "fp-b", AR.AGENT)); assert False
    except VErr:
        pass


def test_failed_submission_is_terminal():
    e = module.LifecycleEvent; events = (); fp = "contract-fp"
    events = module.append_event(events, e("0", "SUB-1", module.DeliveryState.DISPATCHED, "dor-runtime", datetime.now(timezone.utc), fp, AR.RUNTIME))
    events = module.append_event(events, e("1", "SUB-1", module.DeliveryState.IN_PROGRESS, "agent-1", datetime.now(timezone.utc), fp, AR.AGENT))
    events = module.append_event(events, e("2", "SUB-1", module.DeliveryState.SUBMITTED, "agent-1", datetime.now(timezone.utc), fp, AR.AGENT))
    events = module.append_event(events, e("3", "SUB-1", module.DeliveryState.VERIFYING, "verification-runtime", datetime.now(timezone.utc), fp, AR.VERIFICATION_RUNTIME))
    events = module.append_event(events, e("4", "SUB-1", module.DeliveryState.FAILED, "p3-20", datetime.now(timezone.utc), fp, AR.P3_20))
    try:
        module.append_event(events, e("5", "SUB-1", module.DeliveryState.IN_PROGRESS, "agent-1", datetime.now(timezone.utc), fp, AR.AGENT)); assert False
    except ValueError:
        pass
