"""AuthorityAuditSink — optional decision audit port."""
from __future__ import annotations

import pytest

from phase4.authority import (
    AuthorityEngine,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
    NullAuthorityAuditSink,
    RecordingAuthorityAuditSink,
    composite_audit_sink,
)


def _request(**overrides):
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


def _policy(*rules):
    return AuthorityPolicy(policy_id="policy-1", version="1.0.0", rules=tuple(rules))


def _allow():
    return AuthorityRule(
        rule_id="allow-read",
        action="read_file",
        resource_pattern="/documents/*",
        effect=Decision.ALLOW,
    )


def test_null_sink_is_default_and_silent():
    engine = AuthorityEngine(_policy(_allow()), audit_sink=NullAuthorityAuditSink())
    result = engine.evaluate(_request())
    assert result.decision is Decision.ALLOW
    assert len(engine.audit_trail()) == 1


def test_recording_sink_captures_allow_and_deny():
    sink = RecordingAuthorityAuditSink()
    engine = AuthorityEngine(_policy(_allow()), audit_sink=sink)

    allow = engine.evaluate(_request())
    deny = engine.evaluate(_request(action="delete_file"))

    assert allow.decision is Decision.ALLOW
    assert deny.decision is Decision.DENY
    recorded = sink.decisions()
    assert len(recorded) == 2
    assert recorded[0].decision is Decision.ALLOW
    assert recorded[1].decision is Decision.DENY
    assert engine.audit_trail() == recorded


def test_composite_sink_fans_out():
    a = RecordingAuthorityAuditSink()
    b = RecordingAuthorityAuditSink()
    engine = AuthorityEngine(_policy(_allow()), audit_sink=composite_audit_sink(a, b))
    engine.evaluate(_request())
    assert len(a.decisions()) == 1
    assert len(b.decisions()) == 1
    assert a.decisions()[0].request_id == b.decisions()[0].request_id


def test_sink_exception_propagates_after_local_trail():
    class Boom:
        def record(self, decision) -> None:
            raise RuntimeError("sink down")

    engine = AuthorityEngine(_policy(_allow()), audit_sink=Boom())
    with pytest.raises(RuntimeError, match="sink down"):
        engine.evaluate(_request())
    # Local trail still recorded before sink failure
    assert len(engine.audit_trail()) == 1


def test_issue_grant_also_records_via_evaluate():
    sink = RecordingAuthorityAuditSink()
    engine = AuthorityEngine(_policy(_allow()), audit_sink=sink)
    grant = engine.issue_grant(_request())
    assert grant.verified is True
    assert len(sink.decisions()) == 1
    assert sink.decisions()[0].decision is Decision.ALLOW
