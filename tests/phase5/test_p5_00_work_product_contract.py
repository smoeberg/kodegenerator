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


def verify(c, s, *, passed=True):
    return VE().verify(
        c, s, (fact(),), {"impl": "artifact-hash"}, decision_id="DEC-1",
        predicates={"AC-1": lambda facts: passed},
        governed_evidence_fingerprints={"gov-1": "governed-hash"},
        now=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )


def test_positive_path_ends_in_p3_20_decision():
    c = contract(); d = verify(c, submission(c))
    assert d.passed is True
    assert d.verifier == "p3-20"
    assert d.submission_fingerprint == submission(c).submission_fingerprint


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
    s = WP("SUB-2", c.contract_fingerprint, "agent-1", RS("repo", "rev", "tree", True), (), (), datetime.now(timezone.utc))
    assert verify(c, s).passed is False


def test_artifact_fingerprint_mismatch_fails():
    c = contract(); assert verify(c, submission(c, artifact_fingerprint="wrong")).passed is False


def test_artifact_metadata_mismatch_fails():
    c = contract()
    s = WP("SUB-3", c.contract_fingerprint, "agent-1", RS("repo", "rev", "tree", True),
           (SA("impl", AT.FILE, "wrong.py", "artifact-hash"),), (), datetime.now(timezone.utc))
    assert verify(c, s).passed is False


def test_candidate_evidence_cannot_become_authoritative():
    c = contract(); d = verify(c, submission(c, candidate=True))
    assert d.passed is True
    assert d.criterion_results[-1].evidence_ids == ("gov-1",)


def test_missing_governed_evidence_fails():
    c = contract()
    d = VE().verify(c, submission(c), (), {"impl": "artifact-hash"}, decision_id="DEC-2")
    assert d.passed is False


def test_missing_predicate_fails_closed():
    c = contract()
    d = VE().verify(c, submission(c), (fact(),), {"impl": "artifact-hash"},
                    decision_id="DEC-3", governed_evidence_fingerprints={"gov-1": "governed-hash"})
    assert d.passed is False


def test_changed_governed_evidence_fails_closed():
    c = contract()
    try:
        VE().verify(c, submission(c), (fact(),), {"impl": "artifact-hash"}, decision_id="DEC-4",
                    predicates={"AC-1": lambda facts: True},
                    governed_evidence_fingerprints={"gov-1": "changed-hash"})
        assert False
    except VErr:
        pass


def test_only_p3_20_can_verify():
    try:
        VE("agent-1"); assert False
    except VErr:
        pass


def test_lifecycle_is_append_only_and_p3_20_gated():
    e = module.LifecycleEvent; events = ()
    for i, event_type in enumerate((module.DeliveryState.DISPATCHED, module.DeliveryState.IN_PROGRESS, module.DeliveryState.SUBMITTED)):
        events = module.append_event(events, e(str(i), "SUB-1", event_type, "agent-1", datetime.now(timezone.utc)))
    assert module.derive_delivery_state(events) is module.DeliveryState.SUBMITTED
    try:
        module.append_event(events, e("4", "SUB-1", module.DeliveryState.VERIFYING, "agent-1", datetime.now(timezone.utc))); assert False
    except PermissionError:
        pass
    events = module.append_event(events, e("4", "SUB-1", module.DeliveryState.VERIFYING, "p3-20", datetime.now(timezone.utc)))
    events = module.append_event(events, e("5", "SUB-1", module.DeliveryState.PASSED, "p3-20", datetime.now(timezone.utc)))
    assert module.derive_delivery_state(events) is module.DeliveryState.PASSED


def test_failed_submission_is_terminal():
    e = module.LifecycleEvent; events = ()
    for i, event_type in enumerate((module.DeliveryState.DISPATCHED, module.DeliveryState.IN_PROGRESS, module.DeliveryState.SUBMITTED, module.DeliveryState.VERIFYING, module.DeliveryState.FAILED)):
        actor = "p3-20" if event_type in {module.DeliveryState.VERIFYING, module.DeliveryState.FAILED} else "agent-1"
        events = module.append_event(events, e(str(i), "SUB-1", event_type, actor, datetime.now(timezone.utc)))
    try:
        module.append_event(events, e("6", "SUB-1", module.DeliveryState.IN_PROGRESS, "agent-1", datetime.now(timezone.utc))); assert False
    except ValueError:
        pass
