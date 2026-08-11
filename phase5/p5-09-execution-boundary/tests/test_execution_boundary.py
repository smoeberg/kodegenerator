"""P5-09 execution-boundary contract tests.

These tests intentionally target the public P5-09 contract before the
implementation exists.
"""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest


# Expected public API; imports are intentionally RED until implementation lands.
from phase5.p5_09_execution_boundary.execution_boundary import (  # noqa: E402
    ExecutionBoundary,
    ExecutionPolicy,
    ExecutionRequest,
)
from phase5.p5_09_release_resolution.resolution_models import (  # noqa: E402
    ReleaseDisposition,
    ReleaseResolutionRecord,
)


def resolution(disposition: ReleaseDisposition) -> ReleaseResolutionRecord:
    return ReleaseResolutionRecord(
        resolution_id="res-001",
        disposition=disposition,
        resolution_fingerprint="rfp-001",
        reconciliation_fingerprint="recon-001",
        identity_chain=("org-001", "exec-001", "verify-001"),
        provenance=("p5-07-001", "p5-08-001"),
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
    assert result.resolution_fingerprint == "rfp-001"


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
    bad = ReleaseResolutionRecord(
        resolution_id="res-001",
        disposition=ReleaseDisposition.RETRY_REQUESTED,
        resolution_fingerprint="rfp-001",
        reconciliation_fingerprint="recon-001",
        identity_chain=(),
        provenance=(),
    )
    policy = ExecutionPolicy(adapter_id="retry-adapter", authorized=True)
    with pytest.raises(ValueError):
        ExecutionBoundary().prepare(bad, policy)


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
        resolution_fingerprint = "rfp-001"
        reconciliation_fingerprint = "recon-001"
        identity_chain = ("org-001",)
        provenance = ("p5-08-001",)

    policy = ExecutionPolicy(adapter_id="adapter", authorized=True)
    with pytest.raises(ValueError):
        ExecutionBoundary().prepare(FakeResolution(), policy)
