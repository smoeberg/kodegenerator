"""Unit tests for Phase 8 staging certification and reconciliation."""

from __future__ import annotations

import pytest

from ci.staging.staging_certification import (
    CertificationLedger,
    DeploymentSignature,
    reconcile_unknown,
)


def _sig(
    digest: str, pr: int | None = 7, deployment_id: str = "dep-1"
) -> DeploymentSignature:
    return DeploymentSignature(
        repo="smoeberg/kodegenerator",
        pr=pr,
        image="ghcr.io/smoeberg/kodegenerator",
        digest=digest,
        deployment_id=deployment_id,
    )


def test_certify_records_digest() -> None:
    ledger = CertificationLedger()
    entry = ledger.certify(_sig("sha256:aaaa"), gate_run="run-1")
    assert entry["status"] == "certified"
    assert ledger.certified("sha256:aaaa") is True
    assert ledger.known_digest("sha256:aaaa") is True


def test_reject_unknown_digest() -> None:
    ledger = CertificationLedger()
    assert ledger.certified("sha256:unknown") is False
    assert ledger.latest_certified("ghcr.io/smoeberg/kodegenerator") is None


def test_latest_certified_returns_most_recent() -> None:
    ledger = CertificationLedger()
    ledger.certify(
        _sig("sha256:aaa"), gate_run="run-1", now="2026-08-01T00:00:00+00:00"
    )
    ledger.certify(
        _sig("sha256:bbb"), gate_run="run-2", now="2026-08-02T00:00:00+00:00"
    )
    assert ledger.latest_certified("ghcr.io/smoeberg/kodegenerator") == "sha256:bbb"


def test_reconcile_ok_when_observed_matches_certified() -> None:
    ledger = CertificationLedger()
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    result = reconcile_unknown(ledger, _sig("sha256:aaa"))
    assert result.classification == "OK"
    assert bool(result) is True


def test_reconcile_pending_when_status_unknown_and_digest_uncertified() -> None:
    ledger = CertificationLedger()
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    result = reconcile_unknown(ledger, _sig("sha256:zzz"), deployment_state=None)
    assert result.classification == "PENDING"
    assert result.rollback_target == "sha256:aaa"


def test_reconcile_rollback_required_for_uncertified_deployed_digest() -> None:
    ledger = CertificationLedger()
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    result = reconcile_unknown(ledger, _sig("sha256:zzz"), deployment_state="deployed")
    assert result.classification == "ROLLBACK_REQUIRED"
    assert result.rollback_target == "sha256:aaa"


def test_reconcile_drift_when_uncertified_without_rollback_target() -> None:
    ledger = CertificationLedger()
    result = reconcile_unknown(ledger, _sig("sha256:zzz"), deployment_state="deployed")
    assert result.classification == "DRIFT"
    assert result.rollback_target is None


def test_reconcile_mismatch_when_certified_but_not_expected() -> None:
    ledger = CertificationLedger()
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    ledger.certify(_sig("sha256:bbb"), gate_run="run-2")
    result = reconcile_unknown(ledger, _sig("sha256:aaa"), expected_digest="sha256:bbb")
    assert result.classification == "MISMATCH"
    assert result.rollback_target == "sha256:bbb"


def test_fingerprint_is_deterministic() -> None:
    a = _sig("sha256:aaa").fingerprint()
    b = _sig("sha256:aaa").fingerprint()
    assert a == b
    assert len(a) == 64


def test_duplicate_certify_same_gate_is_idempotent() -> None:
    ledger = CertificationLedger()
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    assert len(ledger.entries) == 1


def test_duplicate_certify_conflicting_gate_raises() -> None:
    ledger = CertificationLedger()
    ledger.certify(_sig("sha256:aaa"), gate_run="run-1")
    with pytest.raises(ValueError):
        ledger.certify(_sig("sha256:aaa"), gate_run="run-2")
