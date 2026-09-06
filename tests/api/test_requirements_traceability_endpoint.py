from __future__ import annotations

from datetime import datetime, timezone
import hashlib

from fastapi import HTTPException
import pytest

from api.auth import User
from api.endpoints.requirements_traceability import (
    RequirementTraceabilityCreateRequest,
    create_requirement_traceability,
)
from domain.actor import Actor, ActorType
from domain.organization import Organization
from infrastructure.persistence.delivery_certificate_store import DeliveryCertificateStore
from infrastructure.persistence.models import OrganizationMembershipModel
from phase4.delivery_certificate import DeliveryArtifactFile, DeliveryVerificationCandidate
from phase4.delivery_certification import DeliveryCertificate, DeliveryCertificationResult
from phase4.requirements_traceability import PlanningRequirements, canonical_planning_fingerprint
from runtime.core import DORRuntime


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _seed(runtime: DORRuntime) -> tuple[DeliveryVerificationCandidate, DeliveryCertificate, dict[str, str], PlanningRequirements]:
    runtime.create_organization(Organization(id="org-1", name="Org 1"))
    runtime.register_actor(
        Actor(id="admin", type=ActorType.HUMAN, identity="admin"),
        organization_id="org-1",
    )
    with runtime.database.session() as session:
        now = datetime.now(timezone.utc)
        session.add(
            OrganizationMembershipModel(
                username="admin",
                organization_id="org-1",
                is_admin=True,
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()

    provenance = {
        "intent_id": "intent-1",
        "content_fingerprint": _digest("onboarding"),
        "report_id": _digest("report"),
        "audit_request_fingerprint": _digest("audit-request"),
        "manifest_id": _digest("manifest"),
        "evidence_bundle_id": _digest("bundle"),
        "commit_sha": "abc123",
        "repository": "owner/repo",
        "purpose": "extend",
        "recommendation": "CONTINUE_WITH_GAPS",
    }
    requirements = PlanningRequirements(
        objective="Link requirements to the delivered artifact.",
        acceptance_criteria="The manifest references only certified paths.",
        constraints="Do not grant release authority.",
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
                sha256=_digest("file"),
                byte_count=4,
                mode=0o644,
            ),
        ),
        evidence_ids=(_digest("lint"), _digest("test"), _digest("build")),
    )
    certificate = DeliveryCertificate(
        candidate_id=candidate.candidate_id,
        organization_id="org-1",
        repository="owner/repo",
        result=DeliveryCertificationResult.PASS,
        reason_codes=("verified",),
        apply_record_id=candidate.apply_record_id,
        observed_workspace_fingerprint=_digest("workspace"),
        certified_by="admin",
        certified_at=datetime(2026, 9, 6, 15, 0, tzinfo=timezone.utc),
    )
    with runtime.database.session("org-1") as session:
        DeliveryCertificateStore(session).add(
            command_id="certificate-command",
            candidate=candidate,
            certificate=certificate,
        )
        session.commit()
    return candidate, certificate, provenance, requirements


def _request(
    candidate: DeliveryVerificationCandidate,
    certificate: DeliveryCertificate,
    provenance: dict[str, str],
    requirements: PlanningRequirements,
    *,
    objective_path: str = "src/app.py",
) -> RequirementTraceabilityCreateRequest:
    return RequirementTraceabilityCreateRequest(
        command_id="trace-command-1",
        organization_id="org-1",
        certificate_id=certificate.certificate_id,
        plan_id=candidate.plan_id,
        planning_provenance=provenance,
        requirements=requirements.canonical(),
        links=[
            {
                "kind": "objective",
                "artifact_paths": [objective_path],
                "evidence_ids": [],
                "rationale": "Implementation link.",
            },
            {
                "kind": "acceptance_criteria",
                "artifact_paths": ["src/app.py"],
                "evidence_ids": [candidate.evidence_ids[1]],
                "rationale": "Certified test evidence.",
            },
            {
                "kind": "constraints",
                "artifact_paths": ["src/app.py"],
                "evidence_ids": [candidate.evidence_ids[0]],
                "rationale": "Certified lint evidence.",
            },
        ],
    )


def test_create_and_replay_requirement_traceability(tmp_path) -> None:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'runtime.db'}")
    runtime.boot()
    candidate, certificate, provenance, requirements = _seed(runtime)
    request = _request(candidate, certificate, provenance, requirements)
    user = User(username="admin", organization_id="org-1")

    first = create_requirement_traceability(request, current_user=user, dor=runtime)
    replay = create_requirement_traceability(request, current_user=user, dor=runtime)

    assert first.replayed is False
    assert first.manifest["status"] == "complete"
    assert first.manifest["semantic_result"] is None
    assert first.manifest["release_authority"] is False
    assert replay.replayed is True
    assert replay.manifest["manifest_id"] == first.manifest["manifest_id"]


def test_same_command_with_changed_trace_links_conflicts(tmp_path) -> None:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'runtime.db'}")
    runtime.boot()
    candidate, certificate, provenance, requirements = _seed(runtime)
    user = User(username="admin", organization_id="org-1")
    first = _request(candidate, certificate, provenance, requirements)
    create_requirement_traceability(first, current_user=user, dor=runtime)

    changed = _request(
        candidate,
        certificate,
        provenance,
        requirements,
        objective_path="src/app.py",
    )
    changed.links[0].rationale = "Different trace rationale."

    with pytest.raises(HTTPException) as exc_info:
        create_requirement_traceability(changed, current_user=user, dor=runtime)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"] == "requirement_traceability_command_conflict"
