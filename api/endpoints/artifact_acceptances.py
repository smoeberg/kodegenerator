"""Human-authoritative multi-spec artifact acceptance control-plane API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from domain.principal import Principal
from infrastructure.persistence.artifact_acceptance_store import (
    ArtifactAcceptanceConflictError,
    ArtifactAcceptanceStore,
)
from infrastructure.persistence.delivery_certificate_store import DeliveryCertificateStore
from infrastructure.persistence.models import OrganizationMembershipModel
from infrastructure.persistence.requirements_traceability_store import RequirementTraceabilityStore
from phase4.artifact_acceptance import (
    ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT,
    ArtifactAcceptanceError,
    artifact_acceptance_request_fingerprint,
    build_multi_spec_artifact_acceptance,
    parse_multi_spec_artifact_acceptance,
)
from phase4.delivery_certificate import canonical_digest
from phase4.delivery_certification import (
    DeliveryCertificate,
    DeliveryCertificationResult,
    parse_delivery_verification_candidate,
)
from phase4.requirements_traceability import (
    RequirementTraceabilityError,
    RequirementTraceabilityManifest,
    TraceCoverageStatus,
    parse_requirement_traceability_manifest,
)
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError


router = APIRouter(
    prefix="/api/v1/control-plane/artifact-acceptances",
    tags=["control-plane-v1"],
)


class ArtifactAcceptanceCreateRequest(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    manifest_ids: list[str] = Field(min_length=2, max_length=16)
    acceptance_assertion: Literal["accept_exact_multi_spec_artifact_bundle"]
    rationale: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_canonical(self) -> "ArtifactAcceptanceCreateRequest":
        if self.command_id != self.command_id.strip():
            raise ValueError("command_id must not contain outer whitespace")
        if self.organization_id != self.organization_id.strip():
            raise ValueError("organization_id must not contain outer whitespace")
        if self.rationale != self.rationale.strip():
            raise ValueError("rationale must not contain outer whitespace")
        if len(self.manifest_ids) != len(set(self.manifest_ids)):
            raise ValueError("manifest_ids must be unique")
        for manifest_id in self.manifest_ids:
            if len(manifest_id) != 64 or any(
                character not in "0123456789abcdef" for character in manifest_id
            ):
                raise ValueError("manifest_ids must be lowercase SHA-256 digests")
        return self


class ArtifactAcceptanceCreateResponse(BaseModel):
    command_id: str
    replayed: bool
    acceptance: dict[str, Any]


class ArtifactAcceptanceReadResponse(BaseModel):
    acceptance: dict[str, Any]


class EligibleTraceabilityManifest(BaseModel):
    manifest_id: str
    repository: str
    plan_id: str
    plan_request_fingerprint: str
    certificate_id: str
    candidate_id: str
    status: Literal["complete"]
    requirement_count: int
    created_by: str
    created_at: str


class EligibleTraceabilityResponse(BaseModel):
    manifests: list[EligibleTraceabilityManifest]


def _context(dor: DORRuntime, current_user: User, organization_id: str) -> None:
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"username": current_user.username},
    )
    try:
        dor.establish_context(
            principal=principal,
            organization_id=organization_id,
            actor_id=current_user.username,
        )
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_context_denied"},
        ) from exc


def _require_admin(dor: DORRuntime, current_user: User, organization_id: str) -> None:
    with dor.database.session() as session:
        membership = session.get(
            OrganizationMembershipModel,
            (current_user.username, organization_id),
        )
    if membership is None or membership.is_admin is not True:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_admin_required"},
        )


def _restore_manifest(row) -> RequirementTraceabilityManifest:
    try:
        manifest = parse_requirement_traceability_manifest(row.manifest_payload)
    except RequirementTraceabilityError as exc:
        raise ArtifactAcceptanceError(
            "persisted traceability manifest content identity is invalid"
        ) from exc
    if (
        row.manifest_id != manifest.manifest_id
        or row.organization_id != manifest.organization_id
        or row.certificate_id != manifest.certificate_id
        or row.candidate_id != manifest.candidate_id
        or row.plan_id != manifest.plan_id
        or row.plan_request_fingerprint != manifest.plan_request_fingerprint
        or row.status != manifest.status.value
        or row.created_by != manifest.created_by
    ):
        raise ArtifactAcceptanceError(
            "persisted traceability columns do not match canonical manifest"
        )
    return manifest


def _restore_certificate(row) -> DeliveryCertificate:
    payload = dict(row.certificate_payload)
    certificate_id = payload.get("certificate_id")
    unsigned = dict(payload)
    unsigned.pop("certificate_id", None)
    if certificate_id != row.certificate_id or canonical_digest(unsigned) != certificate_id:
        raise ArtifactAcceptanceError(
            "persisted delivery certificate content identity is invalid"
        )
    try:
        certificate = DeliveryCertificate(
            candidate_id=str(payload["candidate_id"]),
            organization_id=str(payload["organization_id"]),
            repository=str(payload["repository"]),
            result=DeliveryCertificationResult(str(payload["result"])),
            reason_codes=tuple(payload["reason_codes"]),
            apply_record_id=str(payload["apply_record_id"]),
            observed_workspace_fingerprint=str(payload["observed_workspace_fingerprint"]),
            certified_by=str(payload["certified_by"]),
            certified_at=datetime.fromisoformat(str(payload["certified_at"])),
            contract_id=str(payload["contract_id"]),
            contract_version=str(payload["contract_version"]),
            contract_fingerprint=str(payload["contract_fingerprint"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ArtifactAcceptanceError(
            "persisted delivery certificate cannot be reconstructed"
        ) from exc
    if certificate.canonical() != payload:
        raise ArtifactAcceptanceError(
            "persisted delivery certificate fields do not match content identity"
        )
    if (
        row.organization_id != certificate.organization_id
        or row.candidate_id != certificate.candidate_id
        or row.result != certificate.result.value
        or row.contract_fingerprint != certificate.contract_fingerprint
    ):
        raise ArtifactAcceptanceError(
            "persisted delivery certificate columns do not match canonical payload"
        )
    return certificate


def _load_acceptance_inputs(
    dor: DORRuntime,
    *,
    organization_id: str,
    manifest_ids: list[str],
):
    manifests = []
    certificates = []
    candidates = []
    with dor.database.session(organization_id) as session:
        trace_store = RequirementTraceabilityStore(session)
        certificate_store = DeliveryCertificateStore(session)
        for manifest_id in sorted(manifest_ids):
            row = trace_store.get(
                organization_id=organization_id,
                manifest_id=manifest_id,
            )
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": "requirement_traceability_not_found",
                        "manifest_id": manifest_id,
                    },
                )
            try:
                manifest = _restore_manifest(row)
            except ArtifactAcceptanceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "traceability_provenance_invalid", "reason": str(exc)},
                ) from exc
            certificate_row = certificate_store.get(
                organization_id=organization_id,
                certificate_id=manifest.certificate_id,
            )
            if certificate_row is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "traceability_certificate_missing"},
                )
            try:
                certificate = _restore_certificate(certificate_row)
                candidate = parse_delivery_verification_candidate(
                    certificate_row.candidate_payload
                )
            except (ArtifactAcceptanceError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "delivery_provenance_invalid", "reason": str(exc)},
                ) from exc
            manifests.append(manifest)
            certificates.append(certificate)
            candidates.append(candidate)
    return tuple(manifests), tuple(certificates), tuple(candidates)


@router.get(
    "/eligible-manifests",
    response_model=EligibleTraceabilityResponse,
)
def list_eligible_traceability_manifests(
    organization_id: str = Query(..., min_length=1, max_length=128),
    repository: str | None = Query(default=None, min_length=1, max_length=512),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> EligibleTraceabilityResponse:
    """List COMPLETE traceability manifests for GUI multi-spec selection."""
    _context(dor, current_user, organization_id)
    with dor.database.session(organization_id) as session:
        rows = RequirementTraceabilityStore(session).list(
            organization_id=organization_id,
            repository=repository,
            status=TraceCoverageStatus.COMPLETE.value,
            limit=limit,
        )
        manifests: list[EligibleTraceabilityManifest] = []
        for row in rows:
            try:
                manifest = _restore_manifest(row)
            except ArtifactAcceptanceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "traceability_provenance_invalid", "reason": str(exc)},
                ) from exc
            manifests.append(
                EligibleTraceabilityManifest(
                    manifest_id=manifest.manifest_id,
                    repository=manifest.repository,
                    plan_id=manifest.plan_id,
                    plan_request_fingerprint=manifest.plan_request_fingerprint,
                    certificate_id=manifest.certificate_id,
                    candidate_id=manifest.candidate_id,
                    status="complete",
                    requirement_count=len(manifest.requirements),
                    created_by=manifest.created_by,
                    created_at=manifest.created_at.isoformat(),
                )
            )
    return EligibleTraceabilityResponse(manifests=manifests)


@router.post(
    "",
    response_model=ArtifactAcceptanceCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_artifact_acceptance(
    request: ArtifactAcceptanceCreateRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ArtifactAcceptanceCreateResponse:
    """Human-accept one exact multi-spec bundle after server-side provenance checks."""
    _context(dor, current_user, request.organization_id)
    _require_admin(dor, current_user, request.organization_id)
    manifests, certificates, candidates = _load_acceptance_inputs(
        dor,
        organization_id=request.organization_id,
        manifest_ids=request.manifest_ids,
    )
    try:
        acceptance = build_multi_spec_artifact_acceptance(
            manifests=manifests,
            certificates=certificates,
            candidates=candidates,
            accepted_by=current_user.username,
            rationale=request.rationale,
        )
    except (ArtifactAcceptanceError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_artifact_acceptance_bundle", "reason": str(exc)},
        ) from exc
    if acceptance.organization_id != request.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "artifact_acceptance_organization_mismatch"},
        )

    try:
        with dor.database.session(request.organization_id) as session:
            store = ArtifactAcceptanceStore(session)
            existing_command = store.get_for_command(
                organization_id=request.organization_id,
                command_id=request.command_id,
            )
            if existing_command is not None:
                try:
                    existing_acceptance = parse_multi_spec_artifact_acceptance(
                        store.response_payload(existing_command)
                    )
                except ArtifactAcceptanceError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "artifact_acceptance_provenance_invalid"},
                    ) from exc
                if artifact_acceptance_request_fingerprint(
                    existing_acceptance
                ) != artifact_acceptance_request_fingerprint(acceptance):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "artifact_acceptance_command_conflict"},
                    )
                return ArtifactAcceptanceCreateResponse(
                    command_id=request.command_id,
                    replayed=True,
                    acceptance=store.response_payload(existing_command),
                )

            existing_bundle = store.get_for_bundle(
                organization_id=request.organization_id,
                bundle_fingerprint=acceptance.bundle_fingerprint,
                contract_fingerprint=ARTIFACT_ACCEPTANCE_CONTRACT_FINGERPRINT,
            )
            if existing_bundle is not None:
                try:
                    parse_multi_spec_artifact_acceptance(
                        store.response_payload(existing_bundle)
                    )
                except ArtifactAcceptanceError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "artifact_acceptance_provenance_invalid"},
                    ) from exc
                return ArtifactAcceptanceCreateResponse(
                    command_id=request.command_id,
                    replayed=True,
                    acceptance=store.response_payload(existing_bundle),
                )

            row = store.add(command_id=request.command_id, acceptance=acceptance)
            session.commit()
            payload = store.response_payload(row)
    except HTTPException:
        raise
    except ArtifactAcceptanceConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "artifact_acceptance_conflict", "reason": str(exc)},
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "artifact_acceptance_persistence_conflict"},
        ) from exc

    return ArtifactAcceptanceCreateResponse(
        command_id=request.command_id,
        replayed=False,
        acceptance=payload,
    )


@router.get(
    "/{acceptance_id}",
    response_model=ArtifactAcceptanceReadResponse,
)
def get_artifact_acceptance(
    acceptance_id: str,
    organization_id: str = Query(..., min_length=1, max_length=128),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ArtifactAcceptanceReadResponse:
    """Read one immutable acceptance within the authenticated tenant."""
    _context(dor, current_user, organization_id)
    with dor.database.session(organization_id) as session:
        store = ArtifactAcceptanceStore(session)
        row = store.get(
            organization_id=organization_id,
            acceptance_id=acceptance_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "artifact_acceptance_not_found"},
            )
        payload = store.response_payload(row)
    try:
        acceptance = parse_multi_spec_artifact_acceptance(payload)
    except ArtifactAcceptanceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "artifact_acceptance_provenance_invalid"},
        ) from exc
    if acceptance.organization_id != organization_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "artifact_acceptance_tenant_drift"},
        )
    return ArtifactAcceptanceReadResponse(acceptance=acceptance.canonical())
