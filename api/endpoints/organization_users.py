"""Organization-scoped user administration for GUI Settings."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from api.auth import (
    User,
    get_current_active_user,
    get_identity_store,
    get_password_hash,
)
from api.dependencies import get_dor
from domain.actor import Actor, ActorType
from infrastructure.persistence.models import (
    IdentityPrincipalModel,
    OrganizationMembershipModel,
)
from infrastructure.persistence.repositories import RepositoryError
from runtime.core import DORRuntime

router = APIRouter(
    prefix="/api/v1/control-plane/organizations/{organization_id}/users",
    tags=["control-plane-v1"],
)


class OrganizationUserResponse(BaseModel):
    username: str
    email: str | None = None
    full_name: str | None = None
    disabled: bool
    is_admin: bool


class OrganizationUserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=1024)
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    is_admin: bool = False

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip().casefold()
        if not value:
            raise ValueError("Brugernavn er påkrævet")
        return value


class OrganizationUserPatchRequest(BaseModel):
    email: str | None = Field(default=None, max_length=255)
    full_name: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, min_length=12, max_length=1024)
    disabled: bool | None = None
    is_admin: bool | None = None


def _require_admin(dor: DORRuntime, username: str, organization_id: str) -> None:
    with dor.database.session() as session:
        membership = session.get(
            OrganizationMembershipModel,
            (username, organization_id),
        )
    if membership is None or not membership.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_admin_required"},
        )


def _identity_map(dor: DORRuntime, usernames: list[str]) -> dict[str, IdentityPrincipalModel]:
    if not usernames:
        return {}
    with dor.database.session() as session:
        rows = list(
            session.scalars(
                select(IdentityPrincipalModel).where(
                    IdentityPrincipalModel.username.in_(usernames)
                )
            ).all()
        )
    return {row.username: row for row in rows}


@router.get("", response_model=list[OrganizationUserResponse])
def list_organization_users(
    organization_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> list[OrganizationUserResponse]:
    """List users in an organization without credential material."""
    _require_admin(dor, current_user.username, organization_id)
    with dor.database.session() as session:
        memberships = list(
            session.scalars(
                select(OrganizationMembershipModel)
                .where(OrganizationMembershipModel.organization_id == organization_id)
                .order_by(OrganizationMembershipModel.username)
            ).all()
        )
    identities = _identity_map(dor, [item.username for item in memberships])
    result: list[OrganizationUserResponse] = []
    for membership in memberships:
        identity = identities.get(membership.username)
        result.append(
            OrganizationUserResponse(
                username=membership.username,
                email=identity.email if identity is not None else None,
                full_name=identity.full_name if identity is not None else None,
                disabled=identity.disabled if identity is not None else False,
                is_admin=membership.is_admin,
            )
        )
    return result


@router.post(
    "",
    response_model=OrganizationUserResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_organization_user(
    organization_id: str,
    request: OrganizationUserCreateRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> OrganizationUserResponse:
    """Create a durable login and bind it to the selected organization."""
    _require_admin(dor, current_user.username, organization_id)
    store = get_identity_store()
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "durable_identity_store_unavailable",
                "message": "Brugerstyring kræver DORs vedvarende identitetslager.",
            },
        )
    if store.get(request.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "username_already_exists"},
        )

    store.create_if_absent(
        username=request.username,
        hashed_password=get_password_hash(request.password),
        email=request.email.strip() if request.email else None,
        full_name=request.full_name.strip() if request.full_name else None,
        organization_id=organization_id,
    )
    now = datetime.now(timezone.utc)
    try:
        dor.register_actor(
            Actor(
                id=request.username,
                type=ActorType.HUMAN,
                identity=(request.full_name or request.username).strip(),
                created_at=now,
                updated_at=now,
            ),
            organization_id,
        )
    except RepositoryError:
        pass

    try:
        with dor.database.session() as session, session.begin():
            membership = session.get(
                OrganizationMembershipModel,
                (request.username, organization_id),
            )
            if membership is None:
                session.add(
                    OrganizationMembershipModel(
                        username=request.username,
                        organization_id=organization_id,
                        is_admin=request.is_admin,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                membership.is_admin = request.is_admin
                membership.updated_at = now
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "user_membership_conflict"},
        ) from exc

    return OrganizationUserResponse(
        username=request.username,
        email=request.email.strip() if request.email else None,
        full_name=request.full_name.strip() if request.full_name else None,
        disabled=False,
        is_admin=request.is_admin,
    )


@router.patch("/{username}", response_model=OrganizationUserResponse)
def update_organization_user(
    organization_id: str,
    username: str,
    request: OrganizationUserPatchRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> OrganizationUserResponse:
    """Edit profile, password, active state and organization admin access."""
    _require_admin(dor, current_user.username, organization_id)
    username = username.strip().casefold()
    store = get_identity_store()
    if store is None or store.get(username) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "user_not_found"},
        )
    if username == current_user.username and request.disabled is True:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cannot_disable_current_user"},
        )
    if username == current_user.username and request.is_admin is False:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "cannot_remove_own_admin_access"},
        )

    with dor.database.session() as session, session.begin():
        membership = session.get(
            OrganizationMembershipModel,
            (username, organization_id),
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "user_membership_not_found"},
            )
        if request.is_admin is not None:
            membership.is_admin = request.is_admin
        membership.updated_at = datetime.now(timezone.utc)

    identity = store.get(username)
    assert identity is not None
    email = identity.get("email") if request.email is None else request.email.strip() or None
    full_name = (
        identity.get("full_name")
        if request.full_name is None
        else request.full_name.strip() or None
    )
    store.update_profile(username, email=email, full_name=full_name)
    if request.password:
        store.rotate_password(username, get_password_hash(request.password))
    if request.disabled is not None:
        store.set_disabled(username, request.disabled)
    updated = store.get(username)
    assert updated is not None
    with dor.database.session() as session:
        membership = session.get(
            OrganizationMembershipModel,
            (username, organization_id),
        )
    assert membership is not None
    return OrganizationUserResponse(
        username=username,
        email=updated.get("email"),
        full_name=updated.get("full_name"),
        disabled=bool(updated.get("disabled")),
        is_admin=membership.is_admin,
    )
