"""Contract tests for the Phase 4 AI-3 Authority Engine."""
from phase4.authority import (
    AuthorityEngine,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)


def request(**overrides):
    values = dict(
        agent_identity="agent-001",
        action="read_file",
        resource="/documents/report.txt",
        context_packet_id="packet-001",
        agent_role="reader",
        context={"environment": "production"},
    )
    values.update(overrides)
    return AuthorityRequest.create(**values)


def policy(*rules):
    return AuthorityPolicy(policy_id="policy-1", version="1.0.0", rules=tuple(rules))


def allow_read(**kwargs):
    return AuthorityRule(
        rule_id="allow-read",
        action="read_file",
        resource_pattern="/documents/*",
        effect=Decision.ALLOW,
        **kwargs,
    )


def test_explicit_allow():
    engine = AuthorityEngine(policy(allow_read()))
    result = engine.evaluate(request())
    assert result.decision is Decision.ALLOW
    assert result.allowed is True
    assert result.matched_rule_ids == ("allow-read",)


def test_no_matching_rule_fails_closed():
    engine = AuthorityEngine(policy(allow_read()))
    result = engine.evaluate(request(action="delete_file"))
    assert result.decision is Decision.DENY
    assert result.allowed is False
    assert "fail closed" in result.reason


def test_explicit_deny_wins_over_allow():
    deny = AuthorityRule(
        rule_id="deny-secret",
        action="read_file",
        resource_pattern="/documents/secret/*",
        effect=Decision.DENY,
    )
    engine = AuthorityEngine(policy(allow_read(), deny))
    result = engine.evaluate(request(resource="/documents/secret/key.txt"))
    assert result.decision is Decision.DENY
    assert set(result.matched_rule_ids) == {"allow-read", "deny-secret"}


def test_identity_binding_is_explicit():
    rule = allow_read(agent_identity="agent-001")
    engine = AuthorityEngine(policy(rule))
    assert engine.evaluate(request(agent_identity="agent-001")).allowed
    assert not engine.evaluate(request(agent_identity="agent-002")).allowed


def test_role_binding_is_explicit():
    rule = allow_read(agent_role="reader")
    engine = AuthorityEngine(policy(rule))
    assert engine.evaluate(request(agent_role="reader")).allowed
    assert not engine.evaluate(request(agent_role="writer")).allowed


def test_context_constraints_are_explicit():
    rule = allow_read(required_context=(("environment", "production"),))
    engine = AuthorityEngine(policy(rule))
    assert engine.evaluate(request(context={"environment": "production"})).allowed
    assert not engine.evaluate(request(context={"environment": "development"})).allowed


def test_declared_capability_is_not_authority():
    """A capability claim is not consulted by AI-3 and cannot create ALLOW."""
    engine = AuthorityEngine(policy())
    result = engine.evaluate(
        request(context={"declared_capability": "read_file"})
    )
    assert result.decision is Decision.DENY


def test_resource_pattern_is_deterministic():
    engine = AuthorityEngine(policy(allow_read()))
    assert engine.evaluate(request(resource="/documents/a.txt")).allowed
    assert not engine.evaluate(request(resource="/secrets/a.txt")).allowed


def test_policy_rule_ids_must_be_unique():
    rule = allow_read()
    try:
        policy(rule, rule)
        assert False, "duplicate rule IDs must be rejected"
    except ValueError as exc:
        assert "rule IDs" in str(exc)


def test_request_id_is_deterministic_for_same_input():
    first = request()
    second = request()
    assert first.request_id == second.request_id


def test_request_id_changes_when_authorization_question_changes():
    first = request(resource="/documents/a.txt")
    second = request(resource="/documents/b.txt")
    assert first.request_id != second.request_id


def test_decision_is_immutable():
    engine = AuthorityEngine(policy(allow_read()))
    result = engine.evaluate(request())
    try:
        result.decision = Decision.DENY
        assert False, "decision must be immutable"
    except AttributeError:
        pass


def test_audit_trail_preserves_every_decision():
    engine = AuthorityEngine(policy(allow_read()))
    first = engine.evaluate(request())
    second = engine.evaluate(request(action="delete_file"))
    trail = engine.audit_trail()
    assert trail == (first, second)
    assert len(trail) == 2


def test_context_packet_is_bound_to_decision():
    engine = AuthorityEngine(policy(allow_read()))
    result = engine.evaluate(request(context_packet_id="packet-xyz"))
    assert result.context_packet_id == "packet-xyz"


def test_priority_does_not_override_deny_precedence():
    allow = AuthorityRule(
        rule_id="high-allow",
        action="read_file",
        resource_pattern="/documents/*",
        effect=Decision.ALLOW,
        priority=100,
    )
    deny = AuthorityRule(
        rule_id="low-deny",
        action="read_file",
        resource_pattern="/documents/*",
        effect=Decision.DENY,
        priority=0,
    )
    result = AuthorityEngine(policy(allow, deny)).evaluate(request())
    assert result.decision is Decision.DENY
