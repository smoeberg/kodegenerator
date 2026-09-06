"""Authoritative Delivery Contract v1 API for immutable verification candidates."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from api.auth import User, get_current_active_user
from api.dependencies import (
    ImplementationAgentConfigurationError,
    get_dor,
    get_governed_patch_runtime,
)
from domain.principal import Principal
from infrastructure.persistence.delivery_certificate_store import (
    DeliveryCertificateConflictError,
    DeliveryCertificateStore,
)
from infrastructure.persistence.models import OrganizationMembershipModel
from phase4.delivery_certification import (
    DELIVERY_CONTRACT_FINGERPRINT,
    DeliveryCandidateContractError,
    DeliveryCertificationUnavailableError,
    DeliveryCertificationVerifier,
    parse_delivery_verification_candidate,
)
from phase4.implementation_agent import GovernedPatchExecutionRuntime
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError


router = APIRouter(
    prefix="/api/v1/control-plane/delivery-certificates",
    tags=["control-plane-v1"],
)


class DeliveryCertificationRequest(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    candidate: dict[str, Any]

    @model_validator(mode="after")
    def validate_canonical(self) -> "DeliveryCertificationRequest":
        if self.command_id != self.command_id.strip():
            raise ValueError("command_id must not contain outer whitespace")
        if self.organization_id != self.organization_id.strip():
            raise ValueError("organization_id must not contain outer whitespace")
        return self


class DeliveryCertificationResponse(BaseModel):
    command_id: str
    replayed: bool
    certificate: dict[str, Any]


class DeliveryCertificateReadResponse(BaseModel):
    certificate: dict[str, Any]


def _patch_runtime() -> GovernedPatchExecutionRuntime:
    try:
        return get_governed_patch_runtime()
    except ImplementationAgentConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "delivery_certification_unavailable",
                "reason": str(exc),
            },
        ) from exc


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


@router.post(
    "",
    response_model=DeliveryCertificationResponse,
    status_code=status.HTTP_201_CREATED,
)
def certify_delivery(
    request: DeliveryCertificationRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
    patch_runtime: GovernedPatchExecutionRuntime = Depends(_patch_runtime),
) -> DeliveryCertificationResponse:
    """Evaluate and persist one candidate under authoritative Delivery Contract v1.

    The command does not run CI, mutate Git, release, deploy, or grant any such
    authority. In v1 an organization admin must explicitly trigger certification.
    """
    _context(dor, current_user, request.organization_id)
    _require_admin(dor, current_user, request.organization_id)
    try:
        candidate = parse_delivery_verification_candidate(request.candidate)
    except DeliveryCandidateContractError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_delivery_candidate", "reason": str(exc)},
        ) from exc
    if candidate.organization_id != request.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "delivery_candidate_organization_mismatch"},
        )

    with dor.database.session(request.organization_id) as session:
        store = DeliveryCertificateStore(session)
        command_row = store.get_for_command(
            organization_id=request.organization_id,
            command_id=request.command_id,
        )
        if command_row is not None:
            if command_row.candidate_id != candidate.candidate_id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "delivery_certification_command_conflict"},
                )
            return DeliveryCertificationResponse(
                command_id=request.command_id,
                replayed=True,
                certificate=store.response_payload(command_row),
            )
        existing = store.get_for_candidate(
            organization_id=request.organization_id,
            candidate_id=candidate.candidate_id,
            contract_fingerprint=DELIVERY_CONTRACT_FINGERPRINT,
        )
        if existing is not None:
            return DeliveryCertificationResponse(
                command_id=request.command_id,
                replayed=True,
                certificate=store.response_payload(existing),
            )

    try:
        certificate = DeliveryCertificationVerifier().certify(
            candidate,
            patch_runtime=patch_runtime,
            certified_by=current_user.username,
        )
    except DeliveryCertificationUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "delivery_certification_provenance_unavailable",
                "reason": str(exc),
            },
        ) from exc

    try:
        with dor.database.session(request.organization_id) as session:
            store = DeliveryCertificateStore(session)
            row = store.add(
                command_id=request.command_id,
                candidate=candidate,
                certificate=certificate,
            )
            replayed = row.certificate_id != certificate.certificate_id
            session.commit()
            payload = store.response_payload(row)
    except DeliveryCertificateConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "delivery_certification_conflict", "reason": str(exc)},
        ) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "delivery_certification_persistence_conflict"},
        ) from exc

    return DeliveryCertificationResponse(
        command_id=request.command_id,
        replayed=replayed,
        certificate=payload,
    )


@router.get(
    "/{certificate_id}",
    response_model=DeliveryCertificateReadResponse,
)
def get_delivery_certificate(
    certificate_id: str,
    organization_id: str = Query(..., min_length=1, max_length=128),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> DeliveryCertificateReadResponse:
    """Read one immutable certificate within the authenticated organization."""
    _context(dor, current_user, organization_id)
    with dor.database.session(organization_id) as session:
        store = DeliveryCertificateStore(session)
        row = store.get(
            organization_id=organization_id,
            certificate_id=certificate_id,
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "delivery_certificate_not_found"},
            )
        payload = store.response_payload(row)
    return DeliveryCertificateReadResponse(certificate=payload)
