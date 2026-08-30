"""Tests for the tamper-evident hash-chained audit harness."""
from dataclasses import replace

import pytest

from phase6.execution import (
    AuditHarness,
    ChainIntegrityError,
    ExecutionAuditEvent,
    HashChainEntry,
)
from phase6.execution.audit import utc_timestamp


def make_event(outcome: str = "ok") -> ExecutionAuditEvent:
    return ExecutionAuditEvent(
        event_type="sandbox.start",
        execution_id="exec-1",
        adapter_id="bwrap",
        outcome=outcome,
        timestamp=utc_timestamp(),
    )


def test_chain_appends_and_verifies():
    harness = AuditHarness(chain_id="chain-1")
    first = harness.append(make_event("launched"))
    second = harness.append(make_event("success"))
    assert harness.length == 2
    assert first.index == 0
    assert second.previous_hash == first.hash
    assert harness.head_hash == harness.verify()


def test_chain_detects_tampered_event():
    harness = AuditHarness()
    harness.append(make_event("launched"))
    harness.append(make_event("success"))
    tampered = replace(harness.entries()[1].event, outcome="TAMPERED")
    forged = HashChainEntry(
        index=1,
        previous_hash=harness.entries()[1].previous_hash,
        hash=harness.entries()[1].hash,
        event=tampered,
    )
    with pytest.raises(ChainIntegrityError):
        harness.verify_from([harness.entries()[0], forged])


def test_chain_detects_dropped_or_reordered_entries():
    harness = AuditHarness()
    harness.append(make_event("launched"))
    harness.append(make_event("success"))
    # The committed head hash covers the full history: replaying a subset
    # against that head must fail (a dropped entry is an integrity break).
    with pytest.raises(ChainIntegrityError):
        harness.verify_from(
            [harness.entries()[0]],
            expected_head=harness.head_hash,
        )
    # Reordering breaks the link regardless of head.
    with pytest.raises(ChainIntegrityError):
        harness.verify_from([harness.entries()[1], harness.entries()[0]])


def test_verify_from_accepts_external_chain_with_expected_head():
    harness = AuditHarness()
    harness.append(make_event("launched"))
    harness.append(make_event("success"))
    head = harness.verify_from(harness.entries(), expected_head=harness.head_hash)
    assert head == harness.head_hash
    with pytest.raises(ChainIntegrityError):
        harness.verify_from(harness.entries(), expected_head="0" * 64)


def test_entry_and_event_contracts_are_immutable():
    harness = AuditHarness()
    entry = harness.append(make_event())
    with pytest.raises((AttributeError, TypeError)):
        entry.hash = "x"
    with pytest.raises((AttributeError, TypeError)):
        entry.event.outcome = "x"
