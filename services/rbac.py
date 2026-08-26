"""Fine-grained enterprise RBAC with tenant/project scope binding.

Roles: Admin, Lead, Developer, Auditor, ReadOnly.
Permissions: view, write, approve, admin, audit.
Guards can be applied to FastAPI endpoints and worker actions.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional, Set

logger = logging.getLogger(__name__)


class Role(str, Enum):
    ADMIN = "admin"
    LEAD = "lead"
    DEVELOPER = "developer"
    AUDITOR = "auditor"
    READ_ONLY = "readonly"


class Permission(str, Enum):
    VIEW = "view"
    WRITE = "write"
    APPROVE = "approve"
    ADMIN = "admin"
    AUDIT = "audit"


_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.ADMIN: frozenset(Permission),
    Role.LEAD: frozenset(
        {Permission.VIEW, Permission.WRITE, Permission.APPROVE, Permission.AUDIT}
    ),
    Role.DEVELOPER: frozenset({Permission.VIEW, Permission.WRITE}),
    Role.AUDITOR: frozenset({Permission.VIEW, Permission.AUDIT}),
    Role.READ_ONLY: frozenset({Permission.VIEW}),
}


class AccessDenied(PermissionError):
    """Raised when an RBAC check fails."""

    def __init__(
        self,
        message: str,
        *,
        actor_id: str = "",
        permission: Optional[Permission] = None,
        tenant_id: str = "",
        project_id: str = "",
    ) -> None:
        self.actor_id = actor_id
        self.permission = permission
        self.tenant_id = tenant_id
        self.project_id = project_id
        super().__init__(message)


@dataclass(frozen=True)
class Scope:
    """Optional tenant/project binding for a role assignment."""

    tenant_id: Optional[str] = None
    project_id: Optional[str] = None

    def matches(self, *, tenant_id: Optional[str], project_id: Optional[str]) -> bool:
        if self.tenant_id is not None and tenant_id is not None:
            if self.tenant_id != tenant_id:
                return False
        if self.tenant_id is not None and tenant_id is None:
            return False
        if self.project_id is not None and project_id is not None:
            if self.project_id != project_id:
                return False
        if self.project_id is not None and project_id is None:
            return False
        return True


@dataclass(frozen=True)
class RoleBinding:
    """Role assignment for an actor within an optional scope."""

    actor_id: str
    role: Role
    scope: Scope = field(default_factory=Scope)
    extra_permissions: frozenset[Permission] = field(default_factory=frozenset)


@dataclass
class Principal:
    """Authenticated subject used by guards and workers."""

    actor_id: str
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    bindings: tuple[RoleBinding, ...] = ()

    def roles(self) -> Set[Role]:
        return {b.role for b in self.bindings}


class RBACPolicy:
    """In-memory RBAC policy store with scope-aware permission checks."""

    def __init__(
        self,
        *,
        role_permissions: Optional[dict[Role, frozenset[Permission]]] = None,
    ) -> None:
        self._role_permissions = dict(role_permissions or _ROLE_PERMISSIONS)
        self._bindings: dict[str, list[RoleBinding]] = {}

    def bind(self, binding: RoleBinding) -> None:
        bucket = self._bindings.setdefault(binding.actor_id, [])
        bucket[:] = [
            b for b in bucket if not (b.role is binding.role and b.scope == binding.scope)
        ]
        bucket.append(binding)

    def unbind(self, actor_id: str, role: Role, scope: Optional[Scope] = None) -> None:
        scope = scope or Scope()
        bucket = self._bindings.get(actor_id, [])
        self._bindings[actor_id] = [
            b for b in bucket if not (b.role is role and b.scope == scope)
        ]

    def bindings_for(self, actor_id: str) -> list[RoleBinding]:
        return list(self._bindings.get(actor_id, ()))

    def principal(
        self,
        actor_id: str,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Principal:
        return Principal(
            actor_id=actor_id,
            tenant_id=tenant_id,
            project_id=project_id,
            bindings=tuple(self._bindings.get(actor_id, ())),
        )

    def permissions_for(
        self,
        actor_id: str,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Set[Permission]:
        effective: Set[Permission] = set()
        for binding in self._bindings.get(actor_id, ()):
            if not binding.scope.matches(tenant_id=tenant_id, project_id=project_id):
                continue
            effective |= set(self._role_permissions.get(binding.role, frozenset()))
            effective |= set(binding.extra_permissions)
        return effective

    def check(
        self,
        actor_id: str,
        permission: Permission,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> bool:
        return permission in self.permissions_for(
            actor_id, tenant_id=tenant_id, project_id=project_id
        )

    def require(
        self,
        actor_id: str,
        permission: Permission,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        if not self.check(
            actor_id, permission, tenant_id=tenant_id, project_id=project_id
        ):
            raise AccessDenied(
                f"actor {actor_id!r} lacks {permission.value} "
                f"(tenant={tenant_id!r}, project={project_id!r})",
                actor_id=actor_id,
                permission=permission,
                tenant_id=tenant_id or "",
                project_id=project_id or "",
            )


class RBACGuard:
    """Guard usable from FastAPI dependencies and worker action hooks."""

    def __init__(self, policy: RBACPolicy) -> None:
        self.policy = policy

    def enforce(
        self,
        principal: Principal,
        permission: Permission,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Principal:
        tid = tenant_id if tenant_id is not None else principal.tenant_id
        pid = project_id if project_id is not None else principal.project_id
        self.policy.require(
            principal.actor_id, permission, tenant_id=tid, project_id=pid
        )
        return principal

    def require_permission(self, permission: Permission) -> Callable[..., Any]:
        def dependency(principal: Principal) -> Principal:
            return self.enforce(principal, permission)

        dependency.__name__ = f"require_{permission.value}"
        dependency.__doc__ = f"Require RBAC permission {permission.value}."
        return dependency

    def allow_worker_action(
        self,
        principal: Principal,
        action: str,
        *,
        tenant_id: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> None:
        mapping = {
            "claim_task": Permission.WRITE,
            "complete_task": Permission.WRITE,
            "fail_task": Permission.WRITE,
            "approve_patch": Permission.APPROVE,
            "view_queue": Permission.VIEW,
            "admin_scale": Permission.ADMIN,
            "export_audit": Permission.AUDIT,
        }
        perm = mapping.get(action, Permission.WRITE)
        self.enforce(principal, perm, tenant_id=tenant_id, project_id=project_id)
