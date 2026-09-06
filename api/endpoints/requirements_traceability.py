"""Governed requirement-to-artifact traceability over PASS delivery certificates."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from domain.principal import Principal
from infrastructure.persistence.delivery_certificate_store import DeliveryCertificateStore
from infrastructure.persistence.models import OrganizationMembershipModel
from infrastructure.persistence.requirements_traceability_store import (
    RequirementTraceabilityConflictError,
    RequirementTraceabilityStore,
)
from phase4.delivery_certificate import canonical_digest
from phase4.delivery_certification import (
    DeliveryCertificate,
    DeliveryCertificationResult,
    parse_delivery_verification_candidate,
)
from phase4.requirements_traceability import (
    CoverageClaim,
    PlanningRequirements,
    RequirementKind,
    RequirementTraceabilityError,
    build_requirement_traceability_manifest,
    parse_requirement_traceability_manifest,
)
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError


router = APIRouter(
    prefix="/api/v1/control-plane/requirement-traceability",
    tags=["control-plane-v1"],
)


class PlanningRequirementsRequest(BaseModel):
    objective: str = Field(min_length=1, max_length=4_000)
    acceptance_criteria: str = Field(min_length=1, max_length=4_000)
    constraints: str = Field(default="", max_length=4_000)

    @model_validator(mode="after")
    def validate_canonical(self) -> "PlanningRequirementsRequest":
        for name in ("objective", "acceptance_criteria", "constraints"):
            value = getattr(self, name)
            if value != value.strip():
                raise ValueError(f"{name} must not contain outer whitespace")
        return self


class RequirementCoverageLinkRequest(BaseModel):
    kind: Literal["objective", "acceptance_criteria", "constraints"]
    artifact_paths: list[str] = Field(default_factory=list, max_length=64)
    evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    rationale: str = Field(default="", max_length=2_000)

    @model_validator(mode="after")
    def validate_canonical(self) -> "RequirementCoverageLinkRequest":
        if self.rationale != self.rationale.strip():
            raise ValueError("rationale must not contain outer whitespace")
        if len(self.artifact_paths) != len(set(self.artifact_paths)):
            raise ValueError("artifact_paths must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        return self


class RequirementTraceabilityCreateRequest(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    certificate_id: str = Field(min_length=64, max_length=64)
    plan_id: str = Field(min_length=1, max_length=128)
    planning_provenance: dict[str, str]
    requirements: PlanningRequirementsRequest
    links: list[RequirementCoverageLinkRequest] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def validate_canonical(self) -> "RequirementTraceabilityCreateRequest":
        for name in ("command_id", "organization_id", "certificate_id", "plan_id"):
            value = getattr(self, name)
            if value != value.strip():
                raise ValueError(f"{name} must not contain outer whitespace")
        return self


class RequirementTraceabilityCreateResponse(BaseModel):
    command_id: str
    replayed: bool
    manifest: dict[str, Any]


class RequirementTraceabilityReadResponse(BaseModel):
    manifest: dict[str, Any]


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


def _restore_certificate(row) -> DeliveryCertificate:
    payload = dict(row.certificate_payload)
    certificate_id = payload.get("certificate_id")
    unsigned = dict(payload)
    unsigned.pop("certificate_id", None)
    if certificate_id != row.certificate_id or canonical_digest(unsigned) != certificate_id:
        raise RequirementTraceabilityError(
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
        raise RequirementTraceabilityError(
            "persisted delivery certificate cannot be reconstructed"
        ) from exc
    if certificate.canonical() != payload:
        raise RequirementTraceabilityError(
            "persisted delivery certificate fields do not match its content identity"
        )
    return certificate


@router.post(
    "",
    response_model=RequirementTraceabilityCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_requirement_traceability(
    request: RequirementTraceabilityCreateRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> RequirementTraceabilityCreateResponse:
    """Persist one exact traceability manifest rooted in an authoritative PASS certificate.

    This endpoint validates reference integrity only. It does not claim semantic
    requirement satisfaction and grants no release/deploy/merge/execution authority.
    """
    _context(dor, current_user, request.organization_id)
    _require_admin(dor, current_user, request.organization_id)

    with dor.database.session(request.organization_id) as session:
        certificate_row = DeliveryCertificateStore(session).get(
            organization_id=request.organization_id,
            certificate_id=request.certificate_id,
        )
        if certificate_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "delivery_certificate_not_found"},
            )
        try:
            certificate = _restore_certificate(certificate_row)
            candidate = parse_delivery_verification_candidate(
                certificate_row.candidate_payload
            )
        except (RequirementTraceabilityError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "delivery_certificate_provenance_invalid",
                    "reason": str(exc),
                },
            ) from exc

    if certificate.result is not DeliveryCertificationResult.PASS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "delivery_certificate_not_passed"},
        )

    try:
        requirements = PlanningRequirements(
            objective=request.requirements.objective,
            acceptance_criteria=request.requirements.acceptance_criteria,
            constraints=request.requirements.constraints,
        )
        claims = tuple(
            CoverageClaim(
                kind=RequirementKind(item.kind),
                artifact_paths=tuple(item.artifact_paths),
                evidence_ids=tuple(item.evidence_ids),
                rationale=item.rationale,
            )
            for item in request.links
        )
        manifest = build_requirement_traceability_manifest(
            certificate=certificate,
            candidate=candidate,
            plan_id=request.plan_id,
            planning_provenance=request.planning_provenance,
            requirements=requirements,
            claims=claims,
            created_by=current_user.username,
        )
    except (RequirementTraceabilityError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_requirement_traceability", "reason": str(exc)},
        ) from exc

    try:
        with dor.database.session(request.organization_id) as session:
            store = RequirementTraceabilityStore(session)
            existing = store.get_for_command(
                organization_id=request.organization_id,
                command_id=request.command_id,
            )
            if existing is not None:
                if existing.manifest_id != manifest.manifest_id:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={"error": "requirement_traceability_command_conflict"},
                    )
                return RequirementTraceabilityCreateResponse(
                    command_id=request.command_id,
                    replayed=True,
                    manifest=store.response_payload(existing),
                )
            row = store.add(command_id=request.command_id, manifest=manifest)
            replayed = row.manifest_id != manifest.manifest_id
            session.commit()
            payload = store.response_payload(row)
    except HTTPException:
        raise
    except RequirementTraceabilityConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "requirement_traceability_conflict", "reason": str(exc)},
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "requirement_traceability_persistence_conflict"},
        ) from exc

    return RequirementTraceabilityCreateResponse(
        command_id=request.command_id,
        replayed=replayed,
        manifest=payload,
    )


@router.get(
    "/{manifest_id}",
    response_model=RequirementTraceabilityReadResponse,
)
def get_requirement_traceability(
    manifest_id: str,
    organization_id: str = Query(..., min_length=1, max_length=128),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> RequirementTraceabilityReadResponse:
    """Read one immutable traceability manifest within the authenticated tenant."""
    _context(dor, current_user, organization_id)
    with dor.database.session(organization_id) as session:
        store = RequirementTraceabilityStore(session)
        row = store.get(organization_id=organization_id, manifest_id=manifest_id)
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "requirement_traceability_not_found"},
            )
        payload = store.response_payload(row)
    try:
        parse_requirement_traceability_manifest(payload)
    except RequirementTraceabilityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "requirement_traceability_provenance_invalid"},
        ) from exc
    return RequirementTraceabilityReadResponse(manifest=payload)
