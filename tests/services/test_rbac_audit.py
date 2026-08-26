"""Tests for enterprise RBAC and hash-chained audit log."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.enterprise_audit import (
    AuditEvent,
    AuditOutcome,
    AuditingRBACGuard,
    EnterpriseAuditLog,
    GENESIS_HASH,
    export_jsonl,
    export_syslog,
    format_cef,
    format_syslog_rfc5424,
)
from services.rbac import (
    AccessDenied,
    Permission,
    RBACGuard,
    RBACPolicy,
    Role,
    RoleBinding,
    Scope,
)


def test_role_permission_matrix_and_scope_binding():
    policy = RBACPolicy()
    policy.bind(RoleBinding("alice", Role.DEVELOPER, Scope(tenant_id="acme", project_id="p1")))
    policy.bind(RoleBinding("bob", Role.AUDITOR, Scope(tenant_id="acme")))
    policy.bind(RoleBinding("carol", Role.ADMIN, Scope()))

    assert policy.check("alice", Permission.WRITE, tenant_id="acme", project_id="p1")
    assert not policy.check("alice", Permission.WRITE, tenant_id="acme", project_id="p2")
    assert not policy.check("alice", Permission.APPROVE, tenant_id="acme", project_id="p1")

    assert policy.check("bob", Permission.AUDIT, tenant_id="acme")
    assert not policy.check("bob", Permission.WRITE, tenant_id="acme")
    assert not policy.check("bob", Permission.VIEW, tenant_id="other")

    assert policy.check("carol", Permission.ADMIN, tenant_id="any", project_id="any")


def test_guard_blocks_unauthorized_worker_actions():
    policy = RBACPolicy()
    policy.bind(RoleBinding("dev", Role.DEVELOPER, Scope(tenant_id="t1")))
    policy.bind(RoleBinding("lead", Role.LEAD, Scope(tenant_id="t1")))
    guard = RBACGuard(policy)

    dev = policy.principal("dev", tenant_id="t1")
    lead = policy.principal("lead", tenant_id="t1")

    guard.allow_worker_action(dev, "claim_task", tenant_id="t1")
    with pytest.raises(AccessDenied):
        guard.allow_worker_action(dev, "approve_patch", tenant_id="t1")
    guard.allow_worker_action(lead, "approve_patch", tenant_id="t1")

    dep = guard.require_permission(Permission.VIEW)
    assert dep(dev).actor_id == "dev"


def test_audit_log_hash_chain_integrity():
    log = EnterpriseAuditLog()
    e1 = log.append(actor_id="a", action="login", resource="session", outcome="success")
    e2 = log.append(actor_id="a", action="write", resource="file", outcome=AuditOutcome.SUCCESS, tenant_id="t1")
    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.event_hash
    assert log.verify_chain() is True
    assert e1.compute_hash() == e1.event_hash

    log._events[0] = AuditEvent(
        event_id=e1.event_id,
        actor_id="evil",
        action=e1.action,
        resource=e1.resource,
        outcome=e1.outcome,
        timestamp=e1.timestamp,
        prev_hash=e1.prev_hash,
        event_hash=e1.event_hash,
    )
    assert log.verify_chain() is False


def test_export_jsonl_and_syslog_cef(tmp_path: Path):
    log = EnterpriseAuditLog()
    log.append(actor_id="a", action="view", resource="proj", outcome="success", tenant_id="t1")
    log.append(actor_id="b", action="deny", resource="proj", outcome=AuditOutcome.DENIED, tenant_id="t1")
    events = log.events()

    jsonl_path = tmp_path / "audit.jsonl"
    n = export_jsonl(events, jsonl_path)
    assert n == 2
    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "event_hash" in lines[0]

    syslog_path = tmp_path / "audit.syslog"
    assert export_syslog(events, syslog_path, fmt="rfc5424") == 2
    assert "actor=a" in syslog_path.read_text(encoding="utf-8")

    cef_path = tmp_path / "audit.cef"
    assert export_syslog(events, cef_path, fmt="cef") == 2
    cef_body = cef_path.read_text(encoding="utf-8")
    assert cef_body.startswith("CEF:0|")

    assert format_syslog_rfc5424(events[0]).startswith("1 ")
    assert format_cef(events[0]).startswith("CEF:0|")


def test_silent_drop_on_invalid_signature(tmp_path: Path):
    log = EnterpriseAuditLog()
    good = log.append(actor_id="a", action="ok", resource="r", outcome="success")
    bad = AuditEvent(
        event_id="ae_bad",
        actor_id="x",
        action="tamper",
        resource="r",
        outcome=AuditOutcome.SUCCESS,
        timestamp=good.timestamp,
        prev_hash=good.event_hash,
        event_hash="deadbeef",
    )
    path = tmp_path / "mixed.jsonl"
    written = export_jsonl([good, bad], path)
    assert written == 1


def test_auditing_guard_records_allow_and_deny():
    policy = RBACPolicy()
    policy.bind(RoleBinding("ro", Role.READ_ONLY, Scope(tenant_id="t1")))
    audit = EnterpriseAuditLog()
    guard = AuditingRBACGuard(policy, audit)
    principal = policy.principal("ro", tenant_id="t1")

    guard.enforce(principal, Permission.VIEW, tenant_id="t1")
    with pytest.raises(AccessDenied):
        guard.enforce(principal, Permission.WRITE, tenant_id="t1")

    events = audit.events(tenant_id="t1")
    actions = {e.action for e in events}
    assert "rbac.allow.view" in actions
    assert "rbac.deny.write" in actions
    assert audit.verify_chain()
