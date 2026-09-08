"""SC-101B delivery parsing and authoritative current-scope verification."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from phase4.delivery_certificate import (
    DeliveryArtifactFile,
    DeliveryVerificationCandidate,
    DeliveryVerificationStatus,
)
from phase4.delivery_certification import (
    DeliveryCandidateContractError,
    DeliveryCertificate,
    DeliveryCertificationResult,
    DeliveryCertificationVerifier,
)


def parse_scoped_delivery_candidate(payload: Mapping[str, Any]) -> DeliveryVerificationCandidate:
    """Accept the legacy v1 shape or the SC-101B v2 project-bound shape exactly."""
    if not isinstance(payload, Mapping):
        raise DeliveryCandidateContractError("candidate must be an object")
    raw = dict(payload)
    schema_version = raw.get("schema_version")
    if schema_version not in {1, 2}:
        raise DeliveryCandidateContractError("unsupported candidate schema version")
    base_keys = {
        "schema_version", "status", "authoritative", "verification_result",
        "organization_id", "repository", "intent_id", "onboarding_content_fingerprint",
        "audit_report_id", "audit_request_fingerprint", "audit_manifest_id",
        "audit_evidence_bundle_id", "audit_commit_sha", "plan_id",
        "plan_request_fingerprint", "proposal_id", "proposal_request_fingerprint",
        "apply_record_id", "apply_request_fingerprint", "artifact_id", "diff_sha256",
        "baseline_fingerprint", "toolchain_fingerprint", "files", "evidence_ids",
        "candidate_id",
    }
    expected_keys = base_keys | ({"project_id"} if schema_version == 2 else set())
    if set(raw) != expected_keys:
        raise DeliveryCandidateContractError(
            f"candidate fields do not match schema version {schema_version}"
        )
    if raw["status"] != DeliveryVerificationStatus.PENDING_AUTHORITATIVE_VERIFICATION.value:
        raise DeliveryCandidateContractError("candidate is not pending authoritative verification")
    if raw["authoritative"] is not False or raw["verification_result"] is not None:
        raise DeliveryCandidateContractError("handoff candidate cannot claim verification authority")
    raw_files = raw.get("files")
    raw_evidence_ids = raw.get("evidence_ids")
    if not isinstance(raw_files, list) or not isinstance(raw_evidence_ids, list):
        raise DeliveryCandidateContractError("candidate files/evidence are malformed")
    try:
        files = tuple(
            DeliveryArtifactFile(
                path=item["path"],
                exists=item["exists"],
                sha256=item["sha256"],
                byte_count=item["byte_count"],
                mode=item["mode"],
            )
            for item in raw_files
            if isinstance(item, Mapping)
        )
        if len(files) != len(raw_files):
            raise DeliveryCandidateContractError("candidate file manifest is malformed")
        candidate = DeliveryVerificationCandidate(
            organization_id=raw["organization_id"],
            repository=raw["repository"],
            intent_id=raw["intent_id"],
            onboarding_content_fingerprint=raw["onboarding_content_fingerprint"],
            audit_report_id=raw["audit_report_id"],
            audit_request_fingerprint=raw["audit_request_fingerprint"],
            audit_manifest_id=raw["audit_manifest_id"],
            audit_evidence_bundle_id=raw["audit_evidence_bundle_id"],
            audit_commit_sha=raw["audit_commit_sha"],
            plan_id=raw["plan_id"],
            plan_request_fingerprint=raw["plan_request_fingerprint"],
            proposal_id=raw["proposal_id"],
            proposal_request_fingerprint=raw["proposal_request_fingerprint"],
            apply_record_id=raw["apply_record_id"],
            apply_request_fingerprint=raw["apply_request_fingerprint"],
            artifact_id=raw["artifact_id"],
            diff_sha256=raw["diff_sha256"],
            baseline_fingerprint=raw["baseline_fingerprint"],
            toolchain_fingerprint=raw["toolchain_fingerprint"],
            files=files,
            evidence_ids=tuple(raw_evidence_ids),
            project_id=raw.get("project_id"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise DeliveryCandidateContractError(str(exc)) from exc
    if raw["candidate_id"] != candidate.candidate_id or raw != candidate.canonical():
        raise DeliveryCandidateContractError("candidate_id does not match canonical candidate content")
    return candidate


class ProjectScopeDeliveryVerifier:
    """Preserve Delivery Contract v1 evidence while adding the active-scope veto."""

    def certify(
        self,
        candidate: DeliveryVerificationCandidate,
        *,
        patch_runtime: Any,
        active_scope_resolver: Callable[[str, str, str], object],
        certified_by: str,
        certified_at: datetime | None = None,
    ) -> DeliveryCertificate:
        base = DeliveryCertificationVerifier().certify(
            candidate,
            patch_runtime=patch_runtime,
            certified_by=certified_by,
            certified_at=certified_at,
        )
        stale = False
        if candidate.project_id is None:
            stale = True
        else:
            try:
                active_scope_resolver(
                    candidate.organization_id,
                    candidate.project_id,
                    candidate.plan_request_fingerprint,
                )
            except Exception:
                stale = True
        if not stale:
            return base
        reasons = set(base.reason_codes)
        reasons.discard("verified")
        reasons.add("stale_project_scope")
        return DeliveryCertificate(
            candidate_id=candidate.candidate_id,
            organization_id=candidate.organization_id,
            repository=candidate.repository,
            result=DeliveryCertificationResult.FAIL,
            reason_codes=tuple(sorted(reasons)),
            apply_record_id=candidate.apply_record_id,
            observed_workspace_fingerprint=base.observed_workspace_fingerprint,
            certified_by=certified_by,
            certified_at=certified_at or datetime.now(timezone.utc),
        )


__all__ = ["ProjectScopeDeliveryVerifier", "parse_scoped_delivery_candidate"]
