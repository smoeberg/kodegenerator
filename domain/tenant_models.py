"""Multi-tenant isolation domain models.

Defines tenants (organizations), projects, API keys and quota policies used by
:class:`services.tenant_manager.TenantManager` to enforce workspace, disk and
concurrency isolation across organizations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, FrozenSet, Mapping, Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TenantStatus(str, Enum):
    """Lifecycle state of a tenant."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_DELETE = "pending_delete"
    DELETED = "deleted"


class ApiKeyPermission(str, Enum):
    """Capability bits granted to an API key."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    WORKER = "worker"


# Convenience sets for common roles.
PERMISSION_READ_ONLY: FrozenSet[ApiKeyPermission] = frozenset({ApiKeyPermission.READ})
PERMISSION_WORKER: FrozenSet[ApiKeyPermission] = frozenset(
    {ApiKeyPermission.READ, ApiKeyPermission.WORKER}
)
PERMISSION_ADMIN: FrozenSet[ApiKeyPermission] = frozenset(
    {
        ApiKeyPermission.READ,
        ApiKeyPermission.WRITE,
        ApiKeyPermission.ADMIN,
        ApiKeyPermission.WORKER,
    }
)


class QuotaExceededError(RuntimeError):
    """Raised when a tenant exceeds a configured quota."""

    def __init__(self, tenant_id: str, resource: str, message: str) -> None:
        self.tenant_id = tenant_id
        self.resource = resource
        super().__init__(f"[{tenant_id}] quota exceeded for {resource}: {message}")


class TenantAccessError(PermissionError):
    """Raised when an API key or principal lacks required permission."""

    def __init__(self, message: str, *, tenant_id: Optional[str] = None) -> None:
        self.tenant_id = tenant_id
        super().__init__(message)


class TenantNotFoundError(LookupError):
    """Raised when a tenant id is unknown or already wiped."""


@dataclass(frozen=True)
class TenantQuota:
    """Hard limits enforced per tenant."""

    max_disk_bytes: int = 512 * 1024 * 1024  # 512 MiB
    max_concurrent_workers: int = 4
    max_tokens_per_day: int = 1_000_000
    max_projects: int = 50
    max_api_keys: int = 20

    def __post_init__(self) -> None:
        if self.max_disk_bytes < 0:
            raise ValueError("max_disk_bytes must be non-negative")
        if self.max_concurrent_workers < 0:
            raise ValueError("max_concurrent_workers must be non-negative")
        if self.max_tokens_per_day < 0:
            raise ValueError("max_tokens_per_day must be non-negative")
        if self.max_projects < 0:
            raise ValueError("max_projects must be non-negative")
        if self.max_api_keys < 0:
            raise ValueError("max_api_keys must be non-negative")


@dataclass
class Tenant:
    """Isolated organizational boundary."""

    tenant_id: str
    name: str
    status: TenantStatus = TenantStatus.ACTIVE
    quota: TenantQuota = field(default_factory=TenantQuota)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def touch(self) -> None:
        self.updated_at = _utcnow()


@dataclass
class TenantProject:
    """Project scoped strictly to a single tenant."""

    project_id: str
    tenant_id: str
    name: str
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_utcnow)


@dataclass
class ApiKeyRecord:
    """Stored API key material — never keeps the plaintext secret."""

    key_id: str
    tenant_id: str
    name: str
    key_prefix: str
    key_hash: str
    permissions: FrozenSet[ApiKeyPermission]
    created_at: datetime = field(default_factory=_utcnow)
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def has_permission(self, permission: ApiKeyPermission) -> bool:
        if ApiKeyPermission.ADMIN in self.permissions:
            return True
        return permission in self.permissions


@dataclass
class TokenUsageWindow:
    """Rolling daily token counter for a tenant."""

    tenant_id: str
    day_key: str  # YYYY-MM-DD (UTC)
    tokens_used: int = 0

    def remaining(self, quota: TenantQuota) -> int:
        return max(0, quota.max_tokens_per_day - self.tokens_used)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Result of a successful API key authentication."""

    tenant_id: str
    key_id: str
    permissions: FrozenSet[ApiKeyPermission]
    key_name: str

    def require(self, permission: ApiKeyPermission) -> None:
        if ApiKeyPermission.ADMIN in self.permissions:
            return
        if permission not in self.permissions:
            raise TenantAccessError(
                f"API key {self.key_id} lacks permission {permission.value}",
                tenant_id=self.tenant_id,
            )


@dataclass(frozen=True)
class TenantUsageSnapshot:
    """Point-in-time resource usage for observability / status APIs."""

    tenant_id: str
    disk_bytes: int
    disk_quota_bytes: int
    active_workers: int
    worker_quota: int
    tokens_used_today: int
    token_quota: int
    project_count: int
    project_quota: int
    api_key_count: int
    api_key_quota: int

    def to_dict(self) -> Mapping[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "disk_bytes": self.disk_bytes,
            "disk_quota_bytes": self.disk_quota_bytes,
            "active_workers": self.active_workers,
            "worker_quota": self.worker_quota,
            "tokens_used_today": self.tokens_used_today,
            "token_quota": self.token_quota,
            "project_count": self.project_count,
            "project_quota": self.project_quota,
            "api_key_count": self.api_key_count,
            "api_key_quota": self.api_key_quota,
        }
