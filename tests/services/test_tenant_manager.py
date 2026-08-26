"""Tests for multi-tenant isolation (TenantManager)."""
from __future__ import annotations

from pathlib import Path

import pytest

from domain.tenant_models import (
    ApiKeyPermission,
    QuotaExceededError,
    TenantAccessError,
    TenantNotFoundError,
    TenantQuota,
    TenantStatus,
)
from services.tenant_manager import (
    TenantManager,
    hash_api_key,
    verify_api_key,
)


@pytest.fixture()
def manager(tmp_path: Path) -> TenantManager:
    return TenantManager(
        root=tmp_path / "tenants",
        default_quota=TenantQuota(
            max_disk_bytes=10 * 1024 * 1024,
            max_concurrent_workers=2,
            max_tokens_per_day=1000,
            max_projects=3,
            max_api_keys=2,
        ),
    )


def test_create_tenant_provisions_isolated_workspace(manager: TenantManager, tmp_path: Path):
    tenant = manager.create_tenant("acme", "Acme Corp")
    assert tenant.tenant_id == "acme"
    assert tenant.status is TenantStatus.ACTIVE
    ws = manager.workspace_path("acme")
    assert ws.is_dir()
    assert (ws / "projects").is_dir()
    assert (ws / ".tenant").is_file()
    # Second tenant is fully separate
    manager.create_tenant("globex", "Globex")
    assert manager.workspace_path("globex") != ws
    assert manager.workspace_path("globex").is_dir()


def test_project_isolation_and_project_quota(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    p1 = manager.create_project("acme", "proj-1", "First")
    assert p1.tenant_id == "acme"
    assert manager.project_workspace("acme", "proj-1").is_dir()
    manager.create_project("acme", "proj-2", "Second")
    manager.create_project("acme", "proj-3", "Third")
    with pytest.raises(QuotaExceededError) as exc:
        manager.create_project("acme", "proj-4", "Overflow")
    assert exc.value.resource == "projects"
    # Cross-tenant project ids do not collide
    manager.create_tenant("other", "Other")
    manager.create_project("other", "proj-1", "Other first")
    assert manager.get_project("acme", "proj-1").name == "First"
    assert manager.get_project("other", "proj-1").name == "Other first"


def test_api_key_hashing_permissions_and_auth(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    record, secret = manager.issue_api_key(
        "acme",
        "ci-bot",
        [ApiKeyPermission.READ, ApiKeyPermission.WORKER],
    )
    assert record.key_hash != secret
    assert verify_api_key(secret, record.key_hash)
    assert not verify_api_key("wrong-secret", record.key_hash)
    # bcrypt-style hash stored
    assert record.key_hash.startswith("$2")

    principal = manager.authenticate(secret)
    assert principal.tenant_id == "acme"
    assert principal.key_id == record.key_id
    principal.require(ApiKeyPermission.READ)
    principal.require(ApiKeyPermission.WORKER)
    with pytest.raises(TenantAccessError):
        principal.require(ApiKeyPermission.ADMIN)

    with pytest.raises(TenantAccessError):
        manager.authenticate("kg_invalid_key_value_xyz")


def test_api_key_quota_and_revocation(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    r1, s1 = manager.issue_api_key("acme", "k1", ["read"])
    r2, s2 = manager.issue_api_key("acme", "k2", ["write"])
    with pytest.raises(QuotaExceededError) as exc:
        manager.issue_api_key("acme", "k3", ["admin"])
    assert exc.value.resource == "api_keys"

    manager.revoke_api_key("acme", r1.key_id)
    with pytest.raises(TenantAccessError):
        manager.authenticate(s1)
    # Still can auth with second key
    principal = manager.authenticate(s2)
    principal.require(ApiKeyPermission.WRITE)


def test_worker_concurrency_quota(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    assert manager.acquire_worker_slot("acme") == 1
    assert manager.acquire_worker_slot("acme") == 2
    with pytest.raises(QuotaExceededError) as exc:
        manager.acquire_worker_slot("acme")
    assert exc.value.resource == "workers"
    assert manager.release_worker_slot("acme") == 1
    assert manager.acquire_worker_slot("acme") == 2


def test_token_quota_enforcement(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    assert manager.consume_tokens("acme", 400) == 400
    assert manager.consume_tokens("acme", 600) == 1000
    with pytest.raises(QuotaExceededError) as exc:
        manager.consume_tokens("acme", 1)
    assert exc.value.resource == "tokens"
    assert manager.tokens_used_today("acme") == 1000


def test_disk_quota_enforcement(manager: TenantManager):
    # Tiny disk quota so we can trip it with a small file.
    mgr = TenantManager(
        root=manager.root.parent / "disk-tenants",
        default_quota=TenantQuota(max_disk_bytes=64, max_concurrent_workers=1),
    )
    mgr.create_tenant("tiny", "Tiny")
    target = mgr.project_workspace("tiny", "p1") / "blob.bin"
    target.write_bytes(b"x" * 128)
    with pytest.raises(QuotaExceededError) as exc:
        mgr.enforce_disk_quota("tiny")
    assert exc.value.resource == "disk"


def test_suspended_tenant_blocks_mutations(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    manager.suspend_tenant("acme")
    with pytest.raises(TenantAccessError):
        manager.create_project("acme", "p1", "Nope")
    with pytest.raises(TenantAccessError):
        manager.acquire_worker_slot("acme")
    manager.activate_tenant("acme")
    manager.create_project("acme", "p1", "Yes")


def test_tenant_cleanup_wipes_workspace_and_revokes_keys(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    manager.create_project("acme", "p1", "Data")
    secret_file = manager.project_workspace("acme", "p1") / "secret.txt"
    secret_file.write_text("TOP-SECRET-PAYLOAD", encoding="utf-8")
    _record, secret = manager.issue_api_key("acme", "bot", ["admin"])

    ws = manager.workspace_path("acme")
    assert ws.exists()
    manager.delete_tenant("acme", wipe=True)
    assert not ws.exists()
    with pytest.raises(TenantNotFoundError):
        manager.get_tenant("acme")
    with pytest.raises(TenantAccessError):
        manager.authenticate(secret)


def test_usage_snapshot_and_permission_scoped_project_create(manager: TenantManager):
    manager.create_tenant("acme", "Acme")
    admin_rec, admin_secret = manager.issue_api_key(
        "acme", "admin", [ApiKeyPermission.ADMIN]
    )
    admin = manager.authenticate(admin_secret)
    # Admin issues a write key
    write_rec, write_secret = manager.issue_api_key(
        "acme",
        "writer",
        [ApiKeyPermission.READ, ApiKeyPermission.WRITE],
        issuer=admin,
    )
    writer = manager.authenticate(write_secret)
    manager.create_project("acme", "p1", "Scoped", principal=writer)
    manager.consume_tokens("acme", 50)
    manager.acquire_worker_slot("acme")
    snap = manager.usage_snapshot("acme")
    assert snap.project_count == 1
    assert snap.tokens_used_today == 50
    assert snap.active_workers == 1
    assert snap.api_key_count == 2
    assert snap.to_dict()["tenant_id"] == "acme"

    # Read-only principal cannot create projects (slot freed by revoking writer)
    manager.revoke_api_key("acme", write_rec.key_id, principal=admin)
    _ro_rec, ro_secret = manager.issue_api_key(
        "acme", "reader", [ApiKeyPermission.READ], issuer=admin
    )
    reader = manager.authenticate(ro_secret)
    with pytest.raises(TenantAccessError):
        manager.create_project("acme", "p2", "Denied", principal=reader)


def test_hash_helpers_roundtrip():
    secret = "kg_test_secret_value_12345"
    hashed = hash_api_key(secret)
    assert verify_api_key(secret, hashed)
    assert not verify_api_key(secret + "x", hashed)
