"""PC-101 fail-closed verification of exact server-owned completion evidence."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.project import Project, ProjectCompletionRecord, ProjectStatus
from domain.work_queue import WorkUnitState
from infrastructure.persistence.delivery_certificate_models import DeliveryCertificateModel
from infrastructure.persistence.factory_integration_models import FactoryIntegrationReceiptModel
from infrastructure.persistence.requirements_traceability_models import RequirementTraceabilityModel
from infrastructure.persistence.work_queue_repository import WorkUnitRepository
from infrastructure.runtime.work_queue_scope import work_unit_scope


class ProjectCompletionEvidenceError(RuntimeError):
    """Exact completion evidence is unavailable, stale, incomplete, or inconsistent."""


@dataclass(frozen=True)
class ProjectCompletionEvidence:
    onboarding_intent_id: str
    repository_commit_sha: str
    delivery_certificate_id: str
    traceability_manifest_id: str
    integration_receipt_id: str


class ProjectCompletionEvidenceVerifier:
    """Resolve immutable evidence inside the same tenant-scoped DB transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def verify(
        self,
        *,
        project: Project,
        evidence: ProjectCompletionEvidence,
        completed_by: str,
        completed_at,
    ) -> ProjectCompletionRecord:
        if project.status is not ProjectStatus.COMPLETION_PENDING:
            raise ProjectCompletionEvidenceError("project is not completion-pending")
        plan = project.active_plan_request_fingerprint
        if plan is None:
            raise ProjectCompletionEvidenceError("project has no exact active plan")

        self._require_quiescent_scope(project.id, project.organization_id, plan)
        certificate = self._require_delivery_certificate(
            project.organization_id,
            project.id,
            plan,
            evidence.delivery_certificate_id,
        )
        manifest = self._require_traceability_manifest(
            project.organization_id,
            plan,
            evidence.traceability_manifest_id,
            certificate.certificate_id,
            certificate.candidate_id,
        )
        receipt = self._require_integration_receipt(
            project.organization_id,
            evidence.integration_receipt_id,
            certificate.candidate_id,
        )
        integration_head = str(receipt.payload.get("integration_head_sha", ""))
        if integration_head != evidence.repository_commit_sha:
            raise ProjectCompletionEvidenceError(
                "integration receipt does not bind the expected final repository commit"
            )
        if len(integration_head) != 40 or any(c not in "0123456789abcdef" for c in integration_head):
            raise ProjectCompletionEvidenceError("final repository commit is not an exact Git SHA-1")
        candidate = dict(certificate.candidate_payload)
        if candidate.get("intent_id") != evidence.onboarding_intent_id:
            raise ProjectCompletionEvidenceError(
                "delivery candidate does not bind the final onboarding intent"
            )

        # ProjectCompletionRecord is uniformly content-addressed with SHA-256 fields.
        # Preserve the exact Git SHA-1 in the immutable integration receipt and bind
        # its canonical SHA-256 identity here; the record also binds receipt_id, so
        # the exact final Git head is recoverable and tamper-evident without weakening
        # the existing SHA-256 record contract.
        repository_commit_identity = hashlib.sha256(
            integration_head.encode("ascii")
        ).hexdigest()
        return ProjectCompletionRecord(
            organization_id=project.organization_id,
            project_id=project.id,
            final_project_revision=project.revision,
            onboarding_intent_id=evidence.onboarding_intent_id,
            plan_request_fingerprint=plan,
            repository_commit_sha=repository_commit_identity,
            delivery_certificate_ids=(certificate.certificate_id,),
            traceability_manifest_ids=(manifest.manifest_id,),
            integration_evidence_ids=(receipt.receipt_id,),
            completed_by=completed_by,
            completed_at=completed_at,
        )

    def _require_quiescent_scope(
        self,
        project_id: str,
        organization_id: str,
        plan_request_fingerprint: str,
    ) -> None:
        """Require all ordinary WorkUnits for this exact project+plan to be terminal.

        CLAIMED is running work. PENDING/READY/AWAITING_REVIEW/REJECTED are unresolved
        ordinary/governance work. Only APPROVED or FAILED are terminal for closure.
        This also covers the current backend representation of unresolved work gates;
        no organization-wide work is considered.
        """
        repository = WorkUnitRepository(self.session)
        for work_unit in repository.list_for_organization(organization_id):
            try:
                binding = work_unit_scope(work_unit)
            except Exception as exc:
                raise ProjectCompletionEvidenceError(
                    "malformed project-scoped work prevents completion"
                ) from exc
            if binding != (project_id, plan_request_fingerprint):
                continue
            if work_unit.state not in {WorkUnitState.APPROVED, WorkUnitState.FAILED}:
                raise ProjectCompletionEvidenceError(
                    f"project scope still has unresolved work: {work_unit.id}"
                )

    def _require_delivery_certificate(
        self,
        organization_id: str,
        project_id: str,
        plan_request_fingerprint: str,
        certificate_id: str,
    ) -> DeliveryCertificateModel:
        row = self.session.scalar(
            select(DeliveryCertificateModel).where(
                DeliveryCertificateModel.organization_id == organization_id,
                DeliveryCertificateModel.certificate_id == certificate_id,
            )
        )
        if row is None or row.result.lower() != "pass":
            raise ProjectCompletionEvidenceError("final delivery certificate is not PASS")
        candidate = dict(row.candidate_payload)
        if candidate.get("project_id") != project_id:
            raise ProjectCompletionEvidenceError("delivery certificate project binding mismatch")
        if candidate.get("plan_request_fingerprint") != plan_request_fingerprint:
            raise ProjectCompletionEvidenceError("delivery certificate plan binding mismatch")
        if candidate.get("candidate_id") != row.candidate_id:
            raise ProjectCompletionEvidenceError("delivery certificate candidate identity mismatch")
        return row

    def _require_traceability_manifest(
        self,
        organization_id: str,
        plan_request_fingerprint: str,
        manifest_id: str,
        certificate_id: str,
        candidate_id: str,
    ) -> RequirementTraceabilityModel:
        row = self.session.scalar(
            select(RequirementTraceabilityModel).where(
                RequirementTraceabilityModel.organization_id == organization_id,
                RequirementTraceabilityModel.manifest_id == manifest_id,
            )
        )
        if row is None or row.status.lower() != "complete":
            raise ProjectCompletionEvidenceError("final requirement traceability is not COMPLETE")
        if (
            row.plan_request_fingerprint != plan_request_fingerprint
            or row.certificate_id != certificate_id
            or row.candidate_id != candidate_id
        ):
            raise ProjectCompletionEvidenceError("traceability provenance binding mismatch")
        return row

    def _require_integration_receipt(
        self,
        organization_id: str,
        receipt_id: str,
        candidate_id: str,
    ) -> FactoryIntegrationReceiptModel:
        row = self.session.scalar(
            select(FactoryIntegrationReceiptModel).where(
                FactoryIntegrationReceiptModel.organization_id == organization_id,
                FactoryIntegrationReceiptModel.receipt_id == receipt_id,
            )
        )
        if row is None or row.status.lower() != "succeeded":
            raise ProjectCompletionEvidenceError("final assembled-system integration did not succeed")
        payload = dict(row.payload)
        attestation = dict(payload.get("suite_attestation") or [])
        if attestation.get("status") != "passed":
            raise ProjectCompletionEvidenceError("integration suite attestation is not PASS")
        integrated_candidates = set(payload.get("integrated_candidate_ids") or [])
        if candidate_id not in integrated_candidates:
            raise ProjectCompletionEvidenceError(
                "integration receipt does not include the certified delivery candidate"
            )
        if row.fingerprint != row.receipt_id:
            raise ProjectCompletionEvidenceError("integration receipt content identity mismatch")
        return row


__all__ = [
    "ProjectCompletionEvidence",
    "ProjectCompletionEvidenceError",
    "ProjectCompletionEvidenceVerifier",
]
