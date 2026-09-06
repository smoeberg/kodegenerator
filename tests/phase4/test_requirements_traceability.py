from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pytest

from phase4.delivery_certificate import DeliveryArtifactFile, DeliveryVerificationCandidate
from phase4.delivery_certification import DeliveryCertificate, DeliveryCertificationResult
from phase4.requirements_traceability import (
    CoverageClaim,
    PlanningRequirements,
    RequirementKind,
    RequirementTraceabilityError,
    TraceCoverageStatus,
    build_requirement_traceability_manifest,
    canonical_planning_fingerprint,
    parse_requirement_traceability_manifest,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture():
    provenance = {
        "intent_id": "intent-1",
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
    requirements = PlanningRequirements(
        objective="Add governed organization selection.",
        acceptance_criteria="Organization can be selected without typing an ID.",
        constraints="Preserve tenant isolation.",
    )
    plan_fingerprint = canonical_planning_fingerprint(provenance, requirements)
    candidate = DeliveryVerificationCandidate(
        organization_id="org-1",
        repository="owner/repo",
        intent_id="intent-1",
        onboarding_content_fingerprint=provenance["content_fingerprint"],
        audit_report_id=provenance["report_id"],
        audit_request_fingerprint=provenance["audit_request_fingerprint"],
        audit_manifest_id=provenance["manifest_id"],
        audit_evidence_bundle_id=provenance["evidence_bundle_id"],
        audit_commit_sha=provenance["commit_sha"],
        plan_id="plan-1",
        plan_request_fingerprint=plan_fingerprint,
        proposal_id=_digest("proposal"),
        proposal_request_fingerprint=_digest("proposal-request"),
        apply_record_id=_digest("apply-record"),
        apply_request_fingerprint=_digest("apply-request"),
        artifact_id=_digest("artifact"),
        diff_sha256=_digest("diff"),
        baseline_fingerprint=_digest("baseline"),
        toolchain_fingerprint=_digest("toolchain"),
        files=(
            DeliveryArtifactFile(
                path="src/app.py",
                exists=True,
                sha256=_digest("file-content"),
                byte_count=12,
                mode=0o644,
            ),
        ),
        evidence_ids=(_digest("lint"), _digest("test"), _digest("build")),
    )
    certificate = DeliveryCertificate(
        candidate_id=candidate.candidate_id,
        organization_id=candidate.organization_id,
        repository=candidate.repository,
        result=DeliveryCertificationResult.PASS,
        reason_codes=("verified",),
        apply_record_id=candidate.apply_record_id,
        observed_workspace_fingerprint=_digest("workspace"),
        certified_by="admin",
        certified_at=datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc),
    )
    return provenance, requirements, candidate, certificate


def _complete_claims(candidate: DeliveryVerificationCandidate) -> tuple[CoverageClaim, ...]:
    path = candidate.files[0].path
    evidence = candidate.evidence_ids
    return (
        CoverageClaim(
            kind=RequirementKind.OBJECTIVE,
            artifact_paths=(path,),
            rationale="The implementation lives in this file.",
        ),
        CoverageClaim(
            kind=RequirementKind.ACCEPTANCE_CRITERIA,
            artifact_paths=(path,),
            evidence_ids=(evidence[1],),
            rationale="The certified test evidence supports this trace link.",
        ),
        CoverageClaim(
            kind=RequirementKind.CONSTRAINTS,
            artifact_paths=(path,),
            evidence_ids=(evidence[0],),
        ),
    )


def test_complete_manifest_is_content_addressed_without_semantic_authority() -> None:
    provenance, requirements, candidate, certificate = _fixture()
    manifest = build_requirement_traceability_manifest(
        certificate=certificate,
        candidate=candidate,
        plan_id=candidate.plan_id,
        planning_provenance=provenance,
        requirements=requirements,
        claims=_complete_claims(candidate),
        created_by="admin",
        created_at=datetime(2026, 9, 6, 16, 0, tzinfo=timezone.utc),
    )

    assert manifest.status is TraceCoverageStatus.COMPLETE
    assert manifest.semantic_result is None
    assert manifest.release_authority is False
    payload = manifest.canonical()
    assert payload["reference_integrity_verified"] is True
    assert payload["authoritative"] is False
    assert payload["semantic_result"] is None
    assert payload["release_authority"] is False
    assert payload["summary"] == {"total": 3, "linked": 3, "evidenced": 2}
    assert parse_requirement_traceability_manifest(payload).manifest_id == manifest.manifest_id


def test_partial_manifest_does_not_inflate_coverage() -> None:
    provenance, requirements, candidate, certificate = _fixture()
    claims = list(_complete_claims(candidate))
    claims[1] = CoverageClaim(kind=RequirementKind.ACCEPTANCE_CRITERIA)

    manifest = build_requirement_traceability_manifest(
        certificate=certificate,
        candidate=candidate,
        plan_id=candidate.plan_id,
        planning_provenance=provenance,
        requirements=requirements,
        claims=tuple(claims),
        created_by="admin",
    )

    assert manifest.status is TraceCoverageStatus.PARTIAL
    assert manifest.canonical()["summary"]["linked"] == 2


def test_unknown_artifact_path_is_rejected() -> None:
    provenance, requirements, candidate, certificate = _fixture()
    claims = list(_complete_claims(candidate))
    claims[0] = CoverageClaim(
        kind=RequirementKind.OBJECTIVE,
        artifact_paths=("outside.py",),
    )

    with pytest.raises(RequirementTraceabilityError, match="outside the certified artifact"):
        build_requirement_traceability_manifest(
            certificate=certificate,
            candidate=candidate,
            plan_id=candidate.plan_id,
            planning_provenance=provenance,
            requirements=requirements,
            claims=tuple(claims),
            created_by="admin",
        )


def test_unknown_evidence_id_is_rejected() -> None:
    provenance, requirements, candidate, certificate = _fixture()
    claims = list(_complete_claims(candidate))
    claims[0] = CoverageClaim(
        kind=RequirementKind.OBJECTIVE,
        artifact_paths=(candidate.files[0].path,),
        evidence_ids=(_digest("foreign-evidence"),),
    )

    with pytest.raises(RequirementTraceabilityError, match="outside the certified candidate"):
        build_requirement_traceability_manifest(
            certificate=certificate,
            candidate=candidate,
            plan_id=candidate.plan_id,
            planning_provenance=provenance,
            requirements=requirements,
            claims=tuple(claims),
            created_by="admin",
        )


def test_requirements_or_provenance_drift_cannot_match_candidate_plan() -> None:
    provenance, requirements, candidate, certificate = _fixture()
    changed = PlanningRequirements(
        objective=requirements.objective + " Changed.",
        acceptance_criteria=requirements.acceptance_criteria,
        constraints=requirements.constraints,
    )

    with pytest.raises(RequirementTraceabilityError, match="plan fingerprint"):
        build_requirement_traceability_manifest(
            certificate=certificate,
            candidate=candidate,
            plan_id=candidate.plan_id,
            planning_provenance=provenance,
            requirements=changed,
            claims=_complete_claims(candidate),
            created_by="admin",
        )


def test_fail_certificate_cannot_root_traceability() -> None:
    provenance, requirements, candidate, _ = _fixture()
    failed = DeliveryCertificate(
        candidate_id=candidate.candidate_id,
        organization_id=candidate.organization_id,
        repository=candidate.repository,
        result=DeliveryCertificationResult.FAIL,
        reason_codes=("workspace_drift",),
        apply_record_id=candidate.apply_record_id,
        observed_workspace_fingerprint=_digest("workspace-drift"),
        certified_by="admin",
        certified_at=datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc),
    )

    with pytest.raises(RequirementTraceabilityError, match="PASS delivery certificate"):
        build_requirement_traceability_manifest(
            certificate=failed,
            candidate=candidate,
            plan_id=candidate.plan_id,
            planning_provenance=provenance,
            requirements=requirements,
            claims=_complete_claims(candidate),
            created_by="admin",
        )


def test_tampered_serialized_manifest_is_rejected() -> None:
    provenance, requirements, candidate, certificate = _fixture()
    manifest = build_requirement_traceability_manifest(
        certificate=certificate,
        candidate=candidate,
        plan_id=candidate.plan_id,
        planning_provenance=provenance,
        requirements=requirements,
        claims=_complete_claims(candidate),
        created_by="admin",
    )
    payload = manifest.canonical()
    payload["summary"] = {"total": 3, "linked": 0, "evidenced": 0}

    with pytest.raises(RequirementTraceabilityError, match="content identity mismatch"):
        parse_requirement_traceability_manifest(payload)
