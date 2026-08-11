"""P5-09 execution-boundary contract tests.

These tests intentionally target the public P5-09 contract before the
implementation exists.
"""

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
import importlib.util
import sys

import pytest


# P5 phase directories use hyphens and therefore are not valid Python package
# names. Load the merged P5-08 model by file path.
ROOT = Path(__file__).resolve().parents[2]
P508_PATH = ROOT / "p5-08-release-resolution" / "resolution_models.py"
p508_spec = importlib.util.spec_from_file_location("p508_resolution_models", P508_PATH)
p508 = importlib.util.module_from_spec(p508_spec)
sys.modules[p508_spec.name] = p508
assert p508_spec.loader is not None
p508_spec.loader.exec_module(p508)

ReleaseDisposition = p508.ResolutionDisposition
ReleaseResolutionRecord = p508.ReleaseResolutionRecord


# P5-09 implementation is intentionally absent in the RED stage. Load the
# expected public module by its filesystem path rather than inventing an
# underscore package name that cannot correspond to the repository layout.
P509_PATH = ROOT / "p5-09-execution-boundary" / "execution_boundary.py"
p509_spec = importlib.util.spec_from_file_location("p509_execution_boundary", P509_PATH)
if p509_spec is None or p509_spec.loader is None:
    raise ImportError("P5-09 execution_boundary implementation is not available")
p509 = importlib.util.module_from_spec(p509_spec)
sys.modules[p509_spec.name] = p509
p509_spec.loader.exec_module(p509)

ExecutionBoundary = p509.ExecutionBoundary
ExecutionPolicy = p509.ExecutionPolicy
ExecutionRequest = p509.ExecutionRequest


def resolution(disposition: ReleaseDisposition) -> ReleaseResolutionRecord:
    return ReleaseResolutionRecord(
        resolution_id="res-001",
        reconciliation_id="recon-001",
        reconciliation_fingerprint="recon-fp-001",
        dispatch_id="dispatch-001",
        outcome_id="outcome-001",
        finalization_fingerprint="final-001",
        verifier_id="verify-001",
        release_id="release-001",
        disposition=disposition,
        policy_fingerprint="policy-001",
        resolved_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )


def test_no_action_produces_no_execution_request():
    result = ExecutionBoundary().prepare(
        resolution(ReleaseDisposition.NO_ACTION), ExecutionPolicy()
    )
    assert result is None


def test_retry_requires_explicit_authorized_adapter():
    with pytest.raises(PermissionError):
        ExecutionBoundary().prepare(
            resolution(ReleaseDisposition.RETRY_REQUESTED), ExecutionPolicy()
        )


def test_retry_produces_request_only_when_authorized():
    policy = ExecutionPolicy(adapter_id="retry-adapter", authorized=True)
    result = ExecutionBoundary().prepare(
        resolution(ReleaseDisposition.RETRY_REQUESTED), policy
    )
    assert isinstance(result, ExecutionRequest)
    assert result.disposition is ReleaseDisposition.RETRY_REQUESTED
    assert result.resolution_fingerprint == resolution(
        ReleaseDisposition.RETRY_REQUESTED
    ).fingerprint


def test_escalation_requires_explicit_authorized_adapter():
    with pytest.raises(PermissionError):
        ExecutionBoundary().prepare(
            resolution(ReleaseDisposition.ESCALATION_REQUIRED), ExecutionPolicy()
        )


def test_blocked_cannot_become_release_execution():
    policy = ExecutionPolicy(adapter_id="release-adapter", authorized=True)
    with pytest.raises(PermissionError):
        ExecutionBoundary().prepare(
            resolution(ReleaseDisposition.RELEASE_BLOCKED), policy
        )


def test_missing_provenance_fails_closed():
    class MalformedResolution:
        resolution_id = "res-001"
        disposition = ReleaseDisposition.RETRY_REQUESTED
        fingerprint = "rfp-001"
        reconciliation_id = "recon-001"
        reconciliation_fingerprint = "recon-fp-001"
        dispatch_id = ""
        outcome_id = "outcome-001"
        finalization_fingerprint = "final-001"
        verifier_id = "verify-001"
        release_id = "release-001"
        policy_fingerprint = "policy-001"

    policy = ExecutionPolicy(adapter_id="retry-adapter", authorized=True)
    with pytest.raises(ValueError):
        ExecutionBoundary().prepare(MalformedResolution(), policy)


def test_request_is_immutable():
    policy = ExecutionPolicy(adapter_id="retry-adapter", authorized=True)
    result = ExecutionBoundary().prepare(
        resolution(ReleaseDisposition.RETRY_REQUESTED), policy
    )
    with pytest.raises((FrozenInstanceError, TypeError, AttributeError)):
        result.disposition = ReleaseDisposition.ESCALATION_REQUIRED


def test_request_identity_is_deterministic():
    policy = ExecutionPolicy(adapter_id="retry-adapter", authorized=True)
    first = ExecutionBoundary().prepare(
        resolution(ReleaseDisposition.RETRY_REQUESTED), policy
    )
    second = ExecutionBoundary().prepare(
        resolution(ReleaseDisposition.RETRY_REQUESTED), policy
    )
    assert first.request_id == second.request_id


def test_resolution_is_not_mutated():
    original = resolution(ReleaseDisposition.RETRY_REQUESTED)
    before = original
    policy = ExecutionPolicy(adapter_id="retry-adapter", authorized=True)
    ExecutionBoundary().prepare(original, policy)
    assert original == before


def test_unsupported_disposition_fails_closed():
    class FakeResolution:
        resolution_id = "res-001"
        disposition = "UNKNOWN"
        fingerprint = "rfp-001"
        reconciliation_id = "recon-001"
        reconciliation_fingerprint = "recon-fp-001"
        dispatch_id = "dispatch-001"
        outcome_id = "outcome-001"
        finalization_fingerprint = "final-001"
        verifier_id = "verify-001"
        release_id = "release-001"
        policy_fingerprint = "policy-001"

    policy = ExecutionPolicy(adapter_id="adapter", authorized=True)
    with pytest.raises(ValueError):
        ExecutionBoundary().prepare(FakeResolution(), policy)
