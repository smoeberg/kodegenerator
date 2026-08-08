"""Contract tests for DOR AI-1 Agent Registry."""
import pytest

from phase4.agent_registry import (
    AgentIdentity,
    AgentRegistry,
    AgentRole,
    AgentVersion,
    Capability,
    AgentNotFoundError,
    DuplicateIdentityError,
    RegistrationError,
)


def cap(name: str, version: str = "1.0.0") -> Capability:
    return Capability.create(name, AgentVersion.parse(version))


def test_identity_is_deterministic_and_order_independent():
    caps_a = (cap("verify"), cap("inspect"))
    caps_b = (cap("inspect"), cap("verify"))
    a = AgentIdentity.derive("verifier", AgentVersion(1, 0, 0), AgentRole.VERIFIER, caps_a)
    b = AgentIdentity.derive("verifier", AgentVersion(1, 0, 0), AgentRole.VERIFIER, caps_b)
    assert a == b
    assert len(a.value) == 64


def test_identity_changes_when_declaration_changes():
    base = AgentIdentity.derive("verifier", AgentVersion(1, 0, 0), AgentRole.VERIFIER, (cap("verify"),))
    changed = AgentIdentity.derive("verifier", AgentVersion(1, 1, 0), AgentRole.VERIFIER, (cap("verify"),))
    assert base != changed


def test_capability_declaration_is_not_authorization():
    registry = AgentRegistry()
    record = registry.register(
        agent_type="agent",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.OTHER,
        capabilities=(cap("future_capability"),),
    )
    assert record.has_capability("future_capability")


def test_registration_is_immutable():
    registry = AgentRegistry()
    record = registry.register(
        agent_type="agent",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.OTHER,
    )
    with pytest.raises(AttributeError):
        record.agent_type = "tampered"
    with pytest.raises(AttributeError):
        record.capabilities += (cap("x"),)


def test_duplicate_identity_is_rejected():
    registry = AgentRegistry()
    kwargs = dict(agent_type="agent", version=AgentVersion(1, 0, 0), role=AgentRole.OTHER)
    registry.register(**kwargs)
    with pytest.raises(DuplicateIdentityError):
        registry.register(**kwargs)


def test_invalid_registration_fails_closed():
    registry = AgentRegistry()
    with pytest.raises(RegistrationError):
        registry.register(agent_type="", version=AgentVersion(1, 0, 0), role=AgentRole.OTHER)
    assert registry.list() == []


def test_query_by_role_and_capability():
    registry = AgentRegistry()
    registry.register(
        agent_type="verifier",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.VERIFIER,
        capabilities=(cap("verify"),),
    )
    registry.register(
        agent_type="executor",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.EXECUTOR,
        capabilities=(cap("execute"),),
    )
    assert len(registry.list(role=AgentRole.VERIFIER)) == 1
    assert len(registry.list(capability="execute")) == 1


def test_deactivation_preserves_identity_and_audit():
    registry = AgentRegistry()
    record = registry.register(
        agent_type="agent",
        version=AgentVersion(1, 0, 0),
        role=AgentRole.OTHER,
        actor="registrar",
    )
    updated = registry.deactivate(record.identity, actor="admin", reason="revoked")
    assert updated.identity == record.identity
    assert not updated.active
    with pytest.raises(AgentNotFoundError):
        registry.get(record.identity)
    assert registry.get(record.identity, include_inactive=True).active is False
    audit = registry.audit_trail(record.identity)
    assert [e["operation"] for e in audit] == ["registered", "deactivated"]


def test_trust_anchor_participates_in_identity():
    a = AgentIdentity.derive("agent", AgentVersion(1, 0, 0), AgentRole.OTHER, (), "anchor-a")
    b = AgentIdentity.derive("agent", AgentVersion(1, 0, 0), AgentRole.OTHER, (), "anchor-b")
    assert a != b
