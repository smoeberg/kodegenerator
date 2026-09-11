"""Map Control Plane organization-admin membership into canonical runtime authority."""
from __future__ import annotations

import hashlib
from typing import Any

from domain.authority import RoleAssignment, RoleDefinition
from infrastructure.persistence.authority_repositories import AuthorityRepository
from infrastructure.persistence.models import OrganizationMembershipModel

MANAGED_ADMIN_ROLE_NAME = "DOR Control Plane Administrator"
MANAGED_ADMIN_CAPABILITIES = frozenset(
    {
        "bot_catalog.manage",
        "bot_catalog.view",
        "project.create",
    }
)


class ControlPlaneAdminAuthorityError(RuntimeError):
    """Raised when the managed admin authority contract cannot be synchronized safely."""


def managed_admin_role_id(organization_id: str) -> str:
    organization_id = str(organization_id or "").strip()
    if not organization_id:
        raise ValueError("organization_id is required")
    digest = hashlib.sha256(organization_id.encode("utf-8")).hexdigest()[:24]
    return f"control-plane-admin-{digest}"


def sync_control_plane_admin_authority(
    database: Any,
    *,
    username: str,
    organization_id: str,
    is_admin: bool,
) -> None:
    """Synchronize only DOR's managed admin role for one exact tenant.

    The operation never infers cross-tenant authority and never modifies
    independently managed roles. Demotion inactivates only the managed
    assignment, so later promotion can safely reactivate it.
    """
    username = str(username or "").strip()
    organization_id = str(organization_id or "").strip()
    if not username or not organization_id:
        raise ValueError("username and organization_id are required")

    role_id = managed_admin_role_id(organization_id)
    with database.session(organization_id) as session:
        repository = AuthorityRepository(session)
        role = repository.get_role_definition(role_id, organization_id)

        if role is None:
            if not is_admin:
                return
            repository.add_role_definition(
                RoleDefinition(
                    id=role_id,
                    name=MANAGED_ADMIN_ROLE_NAME,
                    organization_id=organization_id,
                    description=(
                        "System-managed authority for organization administrators "
                        "using the first-party Control Plane."
                    ),
                    capabilities=MANAGED_ADMIN_CAPABILITIES,
                )
            )
            session.flush()
            role = repository.get_role_definition(role_id, organization_id)

        if role is None:
            raise ControlPlaneAdminAuthorityError("managed admin role was not persisted")
        if (
            role.name != MANAGED_ADMIN_ROLE_NAME
            or role.organization_id != organization_id
            or role.capabilities != MANAGED_ADMIN_CAPABILITIES
        ):
            raise ControlPlaneAdminAuthorityError(
                "managed admin role conflicts with the canonical authority contract"
            )
        if role.status != "active":
            if not is_admin:
                return
            repository.set_role_definition_status(role_id, organization_id, "active")

        assignment = repository.get_assignment(username, organization_id, role_id)
        if is_admin:
            if assignment is None:
                repository.assign_role(
                    RoleAssignment(
                        actor_id=username,
                        organization_id=organization_id,
                        role_definition_id=role_id,
                    )
                )
            elif assignment.status == "inactive":
                repository.set_assignment_status(
                    username, organization_id, role_id, "active"
                )
            elif assignment.status == "revoked":
                raise ControlPlaneAdminAuthorityError(
                    "revoked managed admin authority cannot be reactivated implicitly"
                )
        elif assignment is not None and assignment.status == "active":
            repository.set_assignment_status(
                username, organization_id, role_id, "inactive"
            )

        session.commit()


def sync_control_plane_admin_membership(
    database: Any,
    *,
    username: str,
    organization_id: str,
) -> bool:
    """Resolve the exact membership flag, then synchronize the managed role.

    Returns the authoritative membership ``is_admin`` value. Missing membership
    is treated as non-admin and never creates authority.
    """
    username = str(username or "").strip()
    organization_id = str(organization_id or "").strip()
    if not username or not organization_id:
        raise ValueError("username and organization_id are required")
    with database.session() as session:
        membership = session.get(
            OrganizationMembershipModel,
            (username, organization_id),
        )
        is_admin = bool(membership is not None and membership.is_admin)
    sync_control_plane_admin_authority(
        database,
        username=username,
        organization_id=organization_id,
        is_admin=is_admin,
    )
    return is_admin
