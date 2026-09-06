from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pytest

from phase4.artifact_acceptance import (
    ArtifactAcceptanceError,
    artifact_acceptance_request_fingerprint,
    build_multi_spec_artifact_acceptance,
    parse_multi_spec_artifact_acceptance,
)
from phase4.delivery_certificate import DeliveryArtifactFile, DeliveryVerificationCandidate
from phase4.delivery_certification import DeliveryCertificate, DeliveryCertificationResult
from phase4.requirements_traceability import (
    CoverageClaim,
    PlanningRequirements,
    RequirementKind,
    build_requirement_traceability_manifest,
    canonical_planning_fingerprint,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provenance() -> dict[str, str]:
    return {
        "intent_id": "intent-acceptance",
        "content_fingerprint": _digest("onboarding"),
        "report_id": _digest("audit-report"),
        "audit_request_fingerprint": _digest("audit-request"),
        "manifest_id": _digest("audit-manifest"),
        "evidence_bundle_id": _digest("audit-evidence"),
        "commit_sha": "abc123",
        "repository": "owner/repo",
        "purpose": "feature",
        "recommendation": "proceed",
    }


def _spec(
    label: str,
    *,
    file_sha: str = "same-file",
    complete: bool = True,
    passed: bool = True,
):
    provenance = _provenance()
    requirements = PlanningRequirements(
        objective=f"Objective {label}",
        acceptance_criteria=f"Acceptance {label}",
        constraints="Preserve governance boundaries.",
    )
    plan_fingerprint = canonical_planning_fingerprint(provenance, requirements)
    candidate = DeliveryVerificationCandidate(
        organization_id="org-1",
        repository="owner/repo",
        intent_id=provenance["intent_id"],
        onboarding_content_fingerprint=provenance["content_fingerprint"],
        audit_report_id=provenance["report_id"],
        audit_request_fingerprint=provenance["audit_request_fingerprint"],
        audit_manifest_id=provenance["manifest_id"],
        audit_evidence_bundle_id=provenance["evidence_bundle_id"],
        audit_commit_sha=provenance["commit_sha"],
        plan_id=f"plan-{label}",
        plan_request_fingerprint=plan_fingerprint,
        proposal_id=_digest(f"proposal-{label}"),
        proposal_request_fingerprint=_digest(f"proposal-request-{label}"),
        apply_record_id=_digest(f"apply-record-{label}"),
        apply_request_fingerprint=_digest(f"apply-request-{label}"),
        artifact_id=_digest(f"artifact-{label}"),
        diff_sha256=_digest(f"diff-{label}"),
        baseline_fingerprint=_digest(f"baseline-{label}"),
        toolchain_fingerprint=_digest("toolchain"),
        files=(
            DeliveryArtifactFile(
                path="src/app.py",
                exists=True,
                sha256=_digest(file_sha),
                byte_count=42,
                mode=0o644,
            ),
        ),
        evidence_ids=(
            _digest(f"lint-{label}"),
            _digest(f"test-{label}"),
            _digest(f"build-{label}"),
        ),
    )
    result = DeliveryCertificationResult.PASS if passed else DeliveryCertificationResult.FAIL
    certificate = DeliveryCertificate(
        candidate_id=candidate.candidate_id,
        organization_id=candidate.organization_id,
        repository=candidate.repository,
        result=result,
        reason_codes=("verified",) if passed else ("workspace_drift",),
        apply_record_id=candidate.apply_record_id,
        observed_workspace_fingerprint=_digest(f"workspace-{file_sha}"),
        certified_by="admin",
        certified_at=datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc),
    )
    path = candidate.files[0].path
    claims = (
        CoverageClaim(
            kind=RequirementKind.OBJECTIVE,
            artifact_paths=(path,),
            rationale=f"Objective trace {label}",
        ),
        CoverageClaim(
            kind=RequirementKind.ACCEPTANCE_CRITERIA,
            artifact_paths=(path,) if complete else (),
            evidence_ids=(candidate.evidence_ids[1],) if complete else (),
            rationale=f"Acceptance trace {label}",
        ),
        CoverageClaim(
            kind=RequirementKind.CONSTRAINTS,
            artifact_paths=(path,),
            evidence_ids=(candidate.evidence_ids[0],),
        ),
    )
    # Traceability itself requires a PASS certificate. For the negative certificate
    # test we build the manifest with an equivalent PASS certificate, then supply
    # the FAIL certificate to the acceptance boundary.
    trace_certificate = certificate
    if not passed:
        trace_certificate = DeliveryCertificate(
            candidate_id=candidate.candidate_id,
            organization_id=candidate.organization_id,
            repository=candidate.repository,
            result=DeliveryCertificationResult.PASS,
            reason_codes=("verified",),
            apply_record_id=candidate.apply_record_id,
            observed_workspace_fingerprint=_digest(f"workspace-{file_sha}"),
            certified_by="admin",
            certified_at=datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc),
        )
    manifest = build_requirement_traceability_manifest(
        certificate=trace_certificate,
        candidate=candidate,
        plan_id=candidate.plan_id,
        planning_provenance=provenance,
        requirements=requirements,
        claims=claims,
        created_by="admin",
        created_at=datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc),
    )
    return manifest, certificate, candidate


def test_multi_spec_acceptance_is_content_addressed_and_authority_scoped() -> None:
    first = _spec("one")
    second = _spec("two")

    acceptance = build_multi_spec_artifact_acceptance(
        manifests=(first[0], second[0]),
        certificates=(first[1], second[1]),
        candidates=(first[2], second[2]),
        accepted_by="admin",
        rationale="Reviewed both exact COMPLETE traceability specs.",
        accepted_at=datetime(2026, 9, 6, 17, 0, tzinfo=timezone.utc),
    )

    payload = acceptance.canonical()
    assert payload["status"] == "accepted"
    assert payload["authoritative"] is True
    assert payload["authority_scope"] == "multi_spec_artifact_acceptance"
    assert payload["human_attested"] is True
    assert payload["machine_semantic_verification"] is None
    assert payload["release_authority"] is False
    assert payload["deploy_authority"] is False
    assert payload["summary"]["spec_count"] == 2
    assert parse_multi_spec_artifact_acceptance(payload).acceptance_id == acceptance.acceptance_id


def test_acceptance_requires_at_least_two_distinct_plan_fingerprints() -> None:
    first = _spec("same")
    # Same canonical spec and same created_at yields the same manifest identity.
    # A second object does not turn one plan into a multi-spec bundle.
    with pytest.raises(ArtifactAcceptanceError, match="manifest IDs must be unique|distinct plan"):
        build_multi_spec_artifact_acceptance(
            manifests=(first[0], first[0]),
            certificates=(first[1], first[1]),
            candidates=(first[2], first[2]),
            accepted_by="admin",
        )


def test_partial_traceability_cannot_be_accepted() -> None:
    first = _spec("one")
    partial = _spec("two", complete=False)

    with pytest.raises(ArtifactAcceptanceError, match="COMPLETE"):
        build_multi_spec_artifact_acceptance(
            manifests=(first[0], partial[0]),
            certificates=(first[1], partial[1]),
            candidates=(first[2], partial[2]),
            accepted_by="admin",
        )


def test_specs_must_resolve_to_same_artifact_file_set() -> None:
    first = _spec("one", file_sha="artifact-a")
    second = _spec("two", file_sha="artifact-b")

    with pytest.raises(ArtifactAcceptanceError, match="same tenant, repository and artifact"):
        build_multi_spec_artifact_acceptance(
            manifests=(first[0], second[0]),
            certificates=(first[1], second[1]),
            candidates=(first[2], second[2]),
            accepted_by="admin",
        )


def test_fail_delivery_certificate_cannot_be_accepted() -> None:
    first = _spec("one")
    failed = _spec("two", passed=False)

    with pytest.raises(ArtifactAcceptanceError, match="PASS delivery certificates"):
        build_multi_spec_artifact_acceptance(
            manifests=(first[0], failed[0]),
            certificates=(first[1], failed[1]),
            candidates=(first[2], failed[2]),
            accepted_by="admin",
        )


def test_command_request_fingerprint_excludes_server_timestamp() -> None:
    first = _spec("one")
    second = _spec("two")
    kwargs = {
        "manifests": (first[0], second[0]),
        "certificates": (first[1], second[1]),
        "candidates": (first[2], second[2]),
        "accepted_by": "admin",
        "rationale": "Exact bundle accepted.",
    }
    earlier = build_multi_spec_artifact_acceptance(
        **kwargs,
        accepted_at=datetime(2026, 9, 6, 17, 0, tzinfo=timezone.utc),
    )
    later = build_multi_spec_artifact_acceptance(
        **kwargs,
        accepted_at=datetime(2026, 9, 6, 17, 1, tzinfo=timezone.utc),
    )

    assert earlier.acceptance_id != later.acceptance_id
    assert artifact_acceptance_request_fingerprint(earlier) == artifact_acceptance_request_fingerprint(later)


def test_tampered_serialized_acceptance_is_rejected() -> None:
    first = _spec("one")
    second = _spec("two")
    acceptance = build_multi_spec_artifact_acceptance(
        manifests=(first[0], second[0]),
        certificates=(first[1], second[1]),
        candidates=(first[2], second[2]),
        accepted_by="admin",
    )
    payload = acceptance.canonical()
    payload["release_authority"] = True

    with pytest.raises(ArtifactAcceptanceError, match="release_authority"):
        parse_multi_spec_artifact_acceptance(payload)
