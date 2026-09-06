"""Authenticated organization management for the first-party Control Plane."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from domain.actor import Actor, ActorType
from domain.organization import Organization
from infrastructure.persistence.database import apply_tenant_context
from infrastructure.persistence.models import OrganizationMembershipModel
from infrastructure.persistence.repositories import OrganizationRepository, RepositoryError
from infrastructure.persistence.uow import UnitOfWork
from runtime.core import DORRuntime


router = APIRouter(
    prefix="/api/v1/control-plane/organizations",
    tags=["control-plane-v1"],
)

_ORGANIZATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class OrganizationCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def validate_canonical(self) -> "OrganizationCreateRequest":
        if self.id != self.id.strip() or not _ORGANIZATION_ID.fullmatch(self.id):
            raise ValueError(
                "id must be canonical and contain only letters, digits, dot, underscore or hyphen"
            )
        if self.name != self.name.strip():
            raise ValueError("name must not contain outer whitespace")
        if self.description != self.description.strip():
            raise ValueError("description must not contain outer whitespace")
        return self


class OrganizationPatchRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_patch(self) -> "OrganizationPatchRequest":
        if self.name is None and self.description is None:
            raise ValueError("at least one of name or description is required")
        if self.name is not None and self.name != self.name.strip():
            raise ValueError("name must not contain outer whitespace")
        if self.description is not None and self.description != self.description.strip():
            raise ValueError("description must not contain outer whitespace")
        return self


class OrganizationResponse(BaseModel):
    id: str
    name: str
    description: str
    is_admin: bool
    created_at: datetime
    updated_at: datetime


class OrganizationListResponse(BaseModel):
    active_organization_id: str | None
    organizations: list[OrganizationResponse]


def _membership_rows(dor: DORRuntime, username: str) -> list[OrganizationMembershipModel]:
    with dor.database.session() as session:
        return list(
            session.scalars(
                select(OrganizationMembershipModel)
                .where(OrganizationMembershipModel.username == username)
                .order_by(OrganizationMembershipModel.organization_id)
            ).all()
        )


def _require_any_admin(dor: DORRuntime, username: str) -> None:
    if not any(item.is_admin for item in _membership_rows(dor, username)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_admin_required"},
        )


def _require_admin_membership(
    session,
    *,
    username: str,
    organization_id: str,
) -> OrganizationMembershipModel:
    membership = session.get(
        OrganizationMembershipModel,
        (username, organization_id),
    )
    if membership is None or not membership.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_admin_required"},
        )
    return membership


def _response(organization: Organization, *, is_admin: bool) -> OrganizationResponse:
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        description=organization.description,
        is_admin=is_admin,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


@router.get("", response_model=OrganizationListResponse)
def list_organizations(
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> OrganizationListResponse:
    """List only organizations explicitly linked to the authenticated principal."""
    memberships = _membership_rows(dor, current_user.username)
    membership_by_id = {item.organization_id: item for item in memberships}
    if not membership_by_id:
        return OrganizationListResponse(
            active_organization_id=None,
            organizations=[],
        )

    with dor.database.session() as session:
        organizations = OrganizationRepository(session).list()
    visible = [
        _response(
            organization,
            is_admin=membership_by_id[organization.id].is_admin,
        )
        for organization in organizations
        if organization.id in membership_by_id
    ]
    visible_ids = {item.id for item in visible}
    active = (
        current_user.organization_id
        if current_user.organization_id in visible_ids
        else (visible[0].id if visible else None)
    )
    return OrganizationListResponse(
        active_organization_id=active,
        organizations=visible,
    )


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization(
    request: OrganizationCreateRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> OrganizationResponse:
    """Create an organization and make the authenticated admin a member/admin."""
    _require_any_admin(dor, current_user.username)
    now = datetime.now(timezone.utc)
    organization = Organization(
        id=request.id,
        name=request.name,
        description=request.description,
        created_at=now,
        updated_at=now,
    )
    actor = Actor(
        id=current_user.username,
        type=ActorType.HUMAN,
        identity=current_user.full_name or current_user.username,
        created_at=now,
        updated_at=now,
    )

    try:
        with dor.database.session() as session:
            if OrganizationRepository(session).get(request.id) is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "organization_already_exists"},
                )
            apply_tenant_context(session, request.id)
            with UnitOfWork(session) as uow:
                uow.organizations.add(organization)
                uow.actors.add(actor, request.id)
                session.add(
                    OrganizationMembershipModel(
                        username=current_user.username,
                        organization_id=request.id,
                        is_admin=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
    except HTTPException:
        raise
    except (IntegrityError, RepositoryError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "organization_create_conflict"},
        ) from exc

    return _response(organization, is_admin=True)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: str,
    request: OrganizationPatchRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> OrganizationResponse:
    """Rename or edit an organization without changing its immutable ID."""
    try:
        with dor.database.session() as session:
            membership = _require_admin_membership(
                session,
                username=current_user.username,
                organization_id=organization_id,
            )
            repository = OrganizationRepository(session)
            organization = repository.get(organization_id)
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "organization_not_found"},
                )
            if request.name is not None:
                organization.name = request.name
            if request.description is not None:
                organization.description = request.description
            organization.updated_at = datetime.now(timezone.utc)
            with UnitOfWork(session) as uow:
                uow.organizations.update(organization)
    except HTTPException:
        raise
    except RepositoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "organization_update_conflict"},
        ) from exc

    return _response(organization, is_admin=membership.is_admin)
