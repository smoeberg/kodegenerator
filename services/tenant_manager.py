"""Multi-tenant project isolation manager.

Enforces workspace directory isolation, disk quotas, concurrency limits,
API-key authentication (bcrypt hashed secrets) and daily token quotas across
organizations. Tenant cleanup performs data sanitization and recursive
workspace wiping.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Set

import bcrypt

from domain.tenant_models import (
    ApiKeyPermission,
    ApiKeyRecord,
    AuthenticatedPrincipal,
    QuotaExceededError,
    Tenant,
    TenantAccessError,
    TenantNotFoundError,
    TenantProject,
    TenantQuota,
    TenantStatus,
    TenantUsageSnapshot,
    TokenUsageWindow,
)

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_KEY_PREFIX_LEN = 8
_BCRYPT_ROUNDS = 12


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _day_key(moment: Optional[datetime] = None) -> str:
    return (moment or _utcnow()).astimezone(timezone.utc).strftime("%Y-%m-%d")


def _validate_id(value: str, *, label: str = "id") -> str:
    if not value or not _SAFE_ID.match(value):
        raise ValueError(
            f"{label} must match {_SAFE_ID.pattern!r} (got {value!r})"
        )
    return value


def hash_api_key(plaintext: str) -> str:
    """Return a bcrypt hash of *plaintext* (UTF-8)."""
    if not plaintext:
        raise ValueError("plaintext API key must be non-empty")
    digest = bcrypt.hashpw(
        plaintext.encode("utf-8"),
        bcrypt.gensalt(rounds=_BCRYPT_ROUNDS),
    )
    return digest.decode("ascii")


def verify_api_key(plaintext: str, key_hash: str) -> bool:
    """Constant-time verification of a plaintext key against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            plaintext.encode("utf-8"),
            key_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def generate_api_key_secret(*, prefix_hint: str = "kg") -> tuple[str, str, str]:
    """Generate ``(key_id, prefix, plaintext_secret)``.

    The plaintext is returned once to the caller and must never be stored.
    Format: ``{prefix_hint}_{key_id}_{random}``.
    """
    key_id = secrets.token_hex(8)
    random_part = secrets.token_urlsafe(24)
    plaintext = f"{prefix_hint}_{key_id}_{random_part}"
    prefix = plaintext[:_KEY_PREFIX_LEN]
    return key_id, prefix, plaintext


class TenantManager:
    """In-process multi-tenant isolation control plane.

    Parameters
    ----------
    root:
        Base directory under which each tenant receives an isolated workspace
        at ``<root>/tenants/<tenant_id>/``.
    default_quota:
        Quota applied to newly created tenants when none is supplied.
    """

    def __init__(
        self,
        root: Optional[Path | str] = None,
        *,
        default_quota: Optional[TenantQuota] = None,
    ) -> None:
        self.root = Path(root or Path.cwd() / ".kodegen" / "tenants").resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.default_quota = default_quota or TenantQuota()
        self._lock = threading.RLock()
        self._tenants: Dict[str, Tenant] = {}
        self._projects: Dict[str, Dict[str, TenantProject]] = {}
        self._api_keys: Dict[str, ApiKeyRecord] = {}
        self._keys_by_tenant: Dict[str, Set[str]] = {}
        self._active_workers: Dict[str, int] = {}
        self._token_windows: Dict[str, TokenUsageWindow] = {}

    def create_tenant(
        self,
        tenant_id: str,
        name: str,
        *,
        quota: Optional[TenantQuota] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> Tenant:
        """Register a tenant and provision its isolated workspace directory."""
        tenant_id = _validate_id(tenant_id, label="tenant_id")
        if not name or not name.strip():
            raise ValueError("tenant name must be non-empty")
        with self._lock:
            if tenant_id in self._tenants:
                raise ValueError(f"tenant already exists: {tenant_id}")
            q = quota or TenantQuota(
                max_disk_bytes=self.default_quota.max_disk_bytes,
                max_concurrent_workers=self.default_quota.max_concurrent_workers,
                max_tokens_per_day=self.default_quota.max_tokens_per_day,
                max_projects=self.default_quota.max_projects,
                max_api_keys=self.default_quota.max_api_keys,
            )
            tenant = Tenant(
                tenant_id=tenant_id,
                name=name.strip(),
                quota=q,
                metadata=dict(metadata or {}),
            )
            workspace = self.workspace_path(tenant_id)
            workspace.mkdir(parents=True, exist_ok=False)
            (workspace / "projects").mkdir()
            (workspace / "tmp").mkdir()
            (workspace / ".tenant").write_text(
                f"tenant_id={tenant_id}\nname={tenant.name}\n",
                encoding="utf-8",
            )
            self._tenants[tenant_id] = tenant
            self._projects[tenant_id] = {}
            self._keys_by_tenant[tenant_id] = set()
            self._active_workers[tenant_id] = 0
            logger.info("created tenant %s workspace=%s", tenant_id, workspace)
            return tenant

    def get_tenant(self, tenant_id: str) -> Tenant:
        with self._lock:
            tenant = self._tenants.get(tenant_id)
            if tenant is None or tenant.status is TenantStatus.DELETED:
                raise TenantNotFoundError(tenant_id)
            return tenant

    def list_tenants(self, *, include_suspended: bool = True) -> list[Tenant]:
        with self._lock:
            out: list[Tenant] = []
            for tenant in self._tenants.values():
                if tenant.status is TenantStatus.DELETED:
                    continue
                if not include_suspended and tenant.status is TenantStatus.SUSPENDED:
                    continue
                out.append(tenant)
            return sorted(out, key=lambda t: t.tenant_id)

    def suspend_tenant(self, tenant_id: str) -> Tenant:
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            tenant.status = TenantStatus.SUSPENDED
            tenant.touch()
            return tenant

    def activate_tenant(self, tenant_id: str) -> Tenant:
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            if tenant.status is TenantStatus.PENDING_DELETE:
                raise TenantAccessError(
                    "cannot activate a tenant pending deletion",
                    tenant_id=tenant_id,
                )
            tenant.status = TenantStatus.ACTIVE
            tenant.touch()
            return tenant

    def delete_tenant(self, tenant_id: str, *, wipe: bool = True) -> None:
        """Mark tenant deleted, revoke keys, optionally wipe the workspace."""
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            tenant.status = TenantStatus.PENDING_DELETE
            tenant.touch()
            for key_id in list(self._keys_by_tenant.get(tenant_id, ())):
                record = self._api_keys.get(key_id)
                if record and record.revoked_at is None:
                    record.revoked_at = _utcnow()
            self._active_workers[tenant_id] = 0
            if wipe:
                self._wipe_workspace_unlocked(tenant_id)
            tenant.status = TenantStatus.DELETED
            tenant.touch()
            logger.info("deleted tenant %s wipe=%s", tenant_id, wipe)

    def workspace_path(self, tenant_id: str) -> Path:
        """Return the absolute, tenant-scoped workspace directory."""
        _validate_id(tenant_id, label="tenant_id")
        return (self.root / tenant_id).resolve()

    def project_workspace(self, tenant_id: str, project_id: str) -> Path:
        """Return (and ensure) the project directory under the tenant workspace."""
        self._require_active(tenant_id)
        _validate_id(project_id, label="project_id")
        path = self.workspace_path(tenant_id) / "projects" / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def disk_usage_bytes(self, tenant_id: str) -> int:
        """Compute recursive disk usage of the tenant workspace."""
        root = self.workspace_path(tenant_id)
        if not root.exists():
            return 0
        total = 0
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                fp = Path(dirpath) / name
                try:
                    total += fp.stat().st_size
                except OSError:
                    continue
        return total

    def enforce_disk_quota(self, tenant_id: str) -> int:
        """Raise :class:`QuotaExceededError` when disk usage exceeds the quota."""
        tenant = self.get_tenant(tenant_id)
        used = self.disk_usage_bytes(tenant_id)
        if used > tenant.quota.max_disk_bytes:
            raise QuotaExceededError(
                tenant_id,
                "disk",
                f"used={used} limit={tenant.quota.max_disk_bytes}",
            )
        return used

    def _wipe_workspace_unlocked(self, tenant_id: str) -> None:
        root = self.workspace_path(tenant_id)
        if root.exists():
            for dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    fp = Path(dirpath) / name
                    try:
                        size = fp.stat().st_size
                        with open(fp, "wb") as handle:
                            handle.write(b"\x00" * min(size, 1024 * 1024))
                    except OSError:
                        continue
            shutil.rmtree(root, ignore_errors=False)
            logger.info("wiped workspace for tenant %s", tenant_id)

    def create_project(
        self,
        tenant_id: str,
        project_id: str,
        name: str,
        *,
        metadata: Optional[Mapping[str, Any]] = None,
        principal: Optional[AuthenticatedPrincipal] = None,
    ) -> TenantProject:
        """Create a project under *tenant_id* and provision its directory."""
        if principal is not None:
            if principal.tenant_id != tenant_id:
                raise TenantAccessError(
                    "principal tenant mismatch",
                    tenant_id=tenant_id,
                )
            principal.require(ApiKeyPermission.WRITE)
        self._require_active(tenant_id)
        project_id = _validate_id(project_id, label="project_id")
        if not name or not name.strip():
            raise ValueError("project name must be non-empty")
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            projects = self._projects.setdefault(tenant_id, {})
            if project_id in projects:
                raise ValueError(f"project already exists: {project_id}")
            if len(projects) >= tenant.quota.max_projects:
                raise QuotaExceededError(
                    tenant_id,
                    "projects",
                    f"limit={tenant.quota.max_projects}",
                )
            project = TenantProject(
                project_id=project_id,
                tenant_id=tenant_id,
                name=name.strip(),
                metadata=dict(metadata or {}),
            )
            projects[project_id] = project
            self.project_workspace(tenant_id, project_id)
            return project

    def get_project(self, tenant_id: str, project_id: str) -> TenantProject:
        with self._lock:
            self.get_tenant(tenant_id)
            project = self._projects.get(tenant_id, {}).get(project_id)
            if project is None:
                raise TenantNotFoundError(f"{tenant_id}/{project_id}")
            return project

    def list_projects(self, tenant_id: str) -> list[TenantProject]:
        with self._lock:
            self.get_tenant(tenant_id)
            return sorted(
                self._projects.get(tenant_id, {}).values(),
                key=lambda p: p.project_id,
            )

    def issue_api_key(
        self,
        tenant_id: str,
        name: str,
        permissions: Iterable[ApiKeyPermission | str],
        *,
        issuer: Optional[AuthenticatedPrincipal] = None,
    ) -> tuple[ApiKeyRecord, str]:
        """Create an API key. Returns ``(record, plaintext_secret)``.

        The plaintext is only returned once and is never persisted.
        """
        self._require_active(tenant_id)
        if issuer is not None:
            if issuer.tenant_id != tenant_id:
                raise TenantAccessError("issuer tenant mismatch", tenant_id=tenant_id)
            issuer.require(ApiKeyPermission.ADMIN)
        if not name or not name.strip():
            raise ValueError("API key name must be non-empty")
        perms = self._normalize_permissions(permissions)
        if not perms:
            raise ValueError("at least one permission is required")

        with self._lock:
            tenant = self.get_tenant(tenant_id)
            active_keys = [
                kid
                for kid in self._keys_by_tenant.get(tenant_id, ())
                if self._api_keys[kid].is_active
            ]
            if len(active_keys) >= tenant.quota.max_api_keys:
                raise QuotaExceededError(
                    tenant_id,
                    "api_keys",
                    f"limit={tenant.quota.max_api_keys}",
                )
            key_id, prefix, plaintext = generate_api_key_secret()
            record = ApiKeyRecord(
                key_id=key_id,
                tenant_id=tenant_id,
                name=name.strip(),
                key_prefix=prefix,
                key_hash=hash_api_key(plaintext),
                permissions=frozenset(perms),
            )
            self._api_keys[key_id] = record
            self._keys_by_tenant.setdefault(tenant_id, set()).add(key_id)
            return record, plaintext

    def authenticate(self, plaintext_key: str) -> AuthenticatedPrincipal:
        """Validate a plaintext API key and return the principal."""
        if not plaintext_key or not plaintext_key.strip():
            raise TenantAccessError("empty API key")
        with self._lock:
            for record in self._api_keys.values():
                if not record.is_active:
                    continue
                if not plaintext_key.startswith(record.key_prefix):
                    continue
                if not verify_api_key(plaintext_key, record.key_hash):
                    continue
                tenant = self._tenants.get(record.tenant_id)
                if tenant is None or tenant.status is not TenantStatus.ACTIVE:
                    raise TenantAccessError(
                        "tenant is not active",
                        tenant_id=record.tenant_id,
                    )
                record.last_used_at = _utcnow()
                return AuthenticatedPrincipal(
                    tenant_id=record.tenant_id,
                    key_id=record.key_id,
                    permissions=record.permissions,
                    key_name=record.name,
                )
        raise TenantAccessError("invalid API key")

    def revoke_api_key(
        self,
        tenant_id: str,
        key_id: str,
        *,
        principal: Optional[AuthenticatedPrincipal] = None,
    ) -> ApiKeyRecord:
        if principal is not None:
            if principal.tenant_id != tenant_id:
                raise TenantAccessError("principal tenant mismatch", tenant_id=tenant_id)
            principal.require(ApiKeyPermission.ADMIN)
        with self._lock:
            self.get_tenant(tenant_id)
            record = self._api_keys.get(key_id)
            if record is None or record.tenant_id != tenant_id:
                raise TenantNotFoundError(key_id)
            if record.revoked_at is None:
                record.revoked_at = _utcnow()
            return record

    def list_api_keys(self, tenant_id: str) -> list[ApiKeyRecord]:
        with self._lock:
            self.get_tenant(tenant_id)
            return sorted(
                (
                    self._api_keys[kid]
                    for kid in self._keys_by_tenant.get(tenant_id, ())
                ),
                key=lambda r: r.key_id,
            )

    def acquire_worker_slot(self, tenant_id: str) -> int:
        """Reserve one concurrent worker slot; raises if the quota is full."""
        self._require_active(tenant_id)
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            current = self._active_workers.get(tenant_id, 0)
            if current >= tenant.quota.max_concurrent_workers:
                raise QuotaExceededError(
                    tenant_id,
                    "workers",
                    f"active={current} limit={tenant.quota.max_concurrent_workers}",
                )
            self._active_workers[tenant_id] = current + 1
            return self._active_workers[tenant_id]

    def release_worker_slot(self, tenant_id: str) -> int:
        with self._lock:
            current = self._active_workers.get(tenant_id, 0)
            self._active_workers[tenant_id] = max(0, current - 1)
            return self._active_workers[tenant_id]

    def active_workers(self, tenant_id: str) -> int:
        with self._lock:
            return self._active_workers.get(tenant_id, 0)

    def consume_tokens(self, tenant_id: str, tokens: int) -> int:
        """Charge *tokens* against the tenant daily quota; return new total."""
        if tokens < 0:
            raise ValueError("tokens must be non-negative")
        self._require_active(tenant_id)
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            window = self._token_window_unlocked(tenant_id)
            projected = window.tokens_used + tokens
            if projected > tenant.quota.max_tokens_per_day:
                raise QuotaExceededError(
                    tenant_id,
                    "tokens",
                    f"used={window.tokens_used}+{tokens} "
                    f"limit={tenant.quota.max_tokens_per_day}",
                )
            window.tokens_used = projected
            return window.tokens_used

    def tokens_used_today(self, tenant_id: str) -> int:
        with self._lock:
            return self._token_window_unlocked(tenant_id).tokens_used

    def usage_snapshot(self, tenant_id: str) -> TenantUsageSnapshot:
        with self._lock:
            tenant = self.get_tenant(tenant_id)
            window = self._token_window_unlocked(tenant_id)
            active_keys = sum(
                1
                for kid in self._keys_by_tenant.get(tenant_id, ())
                if self._api_keys[kid].is_active
            )
            return TenantUsageSnapshot(
                tenant_id=tenant_id,
                disk_bytes=self.disk_usage_bytes(tenant_id),
                disk_quota_bytes=tenant.quota.max_disk_bytes,
                active_workers=self._active_workers.get(tenant_id, 0),
                worker_quota=tenant.quota.max_concurrent_workers,
                tokens_used_today=window.tokens_used,
                token_quota=tenant.quota.max_tokens_per_day,
                project_count=len(self._projects.get(tenant_id, {})),
                project_quota=tenant.quota.max_projects,
                api_key_count=active_keys,
                api_key_quota=tenant.quota.max_api_keys,
            )

    def _require_active(self, tenant_id: str) -> Tenant:
        tenant = self.get_tenant(tenant_id)
        if tenant.status is not TenantStatus.ACTIVE:
            raise TenantAccessError(
                f"tenant {tenant_id} is {tenant.status.value}",
                tenant_id=tenant_id,
            )
        return tenant

    def _token_window_unlocked(self, tenant_id: str) -> TokenUsageWindow:
        today = _day_key()
        window = self._token_windows.get(tenant_id)
        if window is None or window.day_key != today:
            window = TokenUsageWindow(tenant_id=tenant_id, day_key=today, tokens_used=0)
            self._token_windows[tenant_id] = window
        return window

    @staticmethod
    def _normalize_permissions(
        permissions: Iterable[ApiKeyPermission | str],
    ) -> Set[ApiKeyPermission]:
        out: Set[ApiKeyPermission] = set()
        for item in permissions:
            if isinstance(item, ApiKeyPermission):
                out.add(item)
            else:
                out.add(ApiKeyPermission(str(item).lower()))
        return out
