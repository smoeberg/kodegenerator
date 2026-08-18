"""P4-01 — Durable Authority & Replay Ledger adversarial contract tests.

These tests prove the P4-01 invariant:

    For a given ``execution_id`` an adapter may run at most ONE successful
    side-effecting invocation cluster-wide.

P4-00D secures *authenticity* of the AI-3 -> AI-4 grant. P4-01 secures
*single execution over time and across processes* for a genuine, bound grant.

The attacks below (RA-1 .. RA-4) all use a *valid* HMAC grant. They are
rejected by the durable replay ledger, not by P4-00D. Without the ledger,
every one of them yields a second successful adapter invocation.

The suite also pins:

- ``execution_id`` (not ``grant_id``) is the deduplication key, so a fresh
  re-issued genuine grant for the same policy binding replays.
- a new ``policy_version`` produces a new ``execution_id`` (intentional new
  execution, *not* a ledger concern).
- key rotation does not reset the ledger.
- the pending-claim behaviour is policy-driven: fail-closed by default,
  wait-then-return for configured adapters.

The construction seam is the same real ``AuthorityEngine`` /
``ExecutionEngine`` used by P4-00D. ``InProcessLedger`` is the reference
durable implementation; it is shared across engine instances to model
multi-worker / cross-node behaviour and survives engine "restart" (new
engine instance bound to the same ledger).
"""

from __future__ import annotations

from dataclasses import replace
from threading import Event
from typing import Optional

import pytest

from phase4.authority import AuthorityEngine, AuthorityPolicy, AuthorityRule, Decision
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityRequest
from phase4.execution import ExecutionEngine, ExecutionRequest, ExecutionStatus
from phase4.execution.ledger import (
    InProcessLedger,
    PendingClaimOutcome,
    ReplayPolicy,
)

ACTION = "project.audit"
RESOURCE = "org-a/project-1"
ORGANIZATION = "org-a"
ACTOR = "actor-1"
AGENT = "agent-1"
CAPABILITY = "project.audit"
CONTEXT = "context-1"


class CountingAdapter:
    adapter_id = "counting"
    action = ACTION

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, dispatch=None):
        self.calls += 1
        return type("Result", (), {"output": (("ok", "1"),)})()


class BlockingAdapter:
    """Adapter that blocks until released, to model a long in-flight execution."""

    adapter_id = "blocking"
    action = ACTION

    def __init__(self) -> None:
        self.calls = 0
        self.release = Event()
        self.started = Event()

    def execute(self, request, *, dispatch=None):
        self.calls += 1
        self.started.set()
        self.release.wait(5)
        return type("Result", (), {"output": (("ok", "1"),)})()


def authority(version: str = "1") -> AuthorityEngine:
    return AuthorityEngine(
        AuthorityPolicy(
            policy_id="policy-1",
            version=version,
            rules=(
                AuthorityRule(
                    rule_id="allow-1",
                    action=ACTION,
                    resource_pattern="org-a/*",
                    effect=Decision.ALLOW,
                    agent_identity=AGENT,
                ),
            ),
        )
    )


def authority_request() -> AuthorityRequest:
    return AuthorityRequest.create(
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        parameters={"fingerprint": "fp-1"},
        organization_id=ORGANIZATION,
        actor_id=ACTOR,
        capability=CAPABILITY,
        request_id="req-1",
    )


def execution_request(**changes) -> ExecutionRequest:
    base = ExecutionRequest.create(
        request_id="req-1",
        agent_identity=AGENT,
        action=ACTION,
        resource=RESOURCE,
        context_packet_id=CONTEXT,
        parameters={"fingerprint": "fp-1"},
        idempotency_key="idem-1",
        organization_id=ORGANIZATION,
        actor_id=ACTOR,
        capability=CAPABILITY,
    )
    return replace(base, **changes) if changes else base


def grant_for(version: str = "1") -> VerifiedAuthorityGrant:
    decision = authority(version).evaluate(authority_request())
    return VerifiedAuthorityGrant.from_decision(decision)


def _assert_replayed(result, adapter, *, expected_calls: int = 1) -> None:
    """A replayed result must not have invoked the adapter since the last real call."""
    assert result.status is ExecutionStatus.REPLAYED
    assert adapter.calls == expected_calls


# ---------------------------------------------------------------------------
# RA-1 / RA-2 — restart and multi-worker: a second genuine execution of the
# same bound request must NOT run the adapter again.
# ---------------------------------------------------------------------------


def test_ra1_restart_replays_without_a_second_adapter_call():
    ledger = InProcessLedger()
    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger)

    first = engine.execute(execution_request(), grant_for())
    assert first.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    # "Restart": a brand-new engine bound to the *same* durable ledger.
    restarted = ExecutionEngine((adapter,), ledger=ledger)
    second = restarted.execute(execution_request(), grant_for())
    _assert_replayed(second, adapter)
    assert second.execution_id == first.execution_id


def test_ra2_two_workers_share_one_ledger_and_dedup():
    ledger = InProcessLedger()
    adapter = CountingAdapter()

    worker_a = ExecutionEngine((adapter,), ledger=ledger)
    worker_b = ExecutionEngine((adapter,), ledger=ledger)

    a = worker_a.execute(execution_request(), grant_for())
    assert a.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    b = worker_b.execute(execution_request(), grant_for())
    _assert_replayed(b, adapter)


# ---------------------------------------------------------------------------
# RA-3 — crash during the adapter call. A pending claim must prevent a
# concurrent double-dispatch while the first execution is in flight.
# ---------------------------------------------------------------------------


def test_ra3_pending_claim_default_rejects_concurrent_dispatch():
    ledger = InProcessLedger()
    adapter = BlockingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger)

    from threading import Thread

    def run_first():
        engine.execute(execution_request(), grant_for())

    t = Thread(target=run_first)
    t.start()
    assert adapter.started.wait(5)

    # While the first execution is in flight, a concurrent caller is rejected
    # by the fail-closed pending claim.
    competitor = CountingAdapter()
    competitor_engine = ExecutionEngine((competitor,), ledger=ledger)
    result = competitor_engine.execute(execution_request(), grant_for())
    assert result.status is ExecutionStatus.REJECTED
    assert competitor.calls == 0  # fail-closed: no adapter invocation

    adapter.release.set()
    t.join(5)


def test_ra3_pending_claim_wait_returns_same_terminal_result_when_configured():
    ledger = InProcessLedger()
    policy = ReplayPolicy(pending_claim=PendingClaimOutcome.WAIT)
    adapter = BlockingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger, replay_policy=policy)

    from threading import Thread

    def run_first():
        engine.execute(execution_request(), grant_for())

    t = Thread(target=run_first)
    t.start()
    assert adapter.started.wait(5)

    competitor = CountingAdapter()
    competitor_engine = ExecutionEngine((competitor,), ledger=ledger, replay_policy=policy)
    result = competitor_engine.execute(execution_request(), grant_for())
    _assert_replayed(result, competitor, expected_calls=0)

    adapter.release.set()
    t.join(5)


# ---------------------------------------------------------------------------
# RA-4 — a leaked genuine grant used on a second node sharing the ledger is
# still deduplicated by execution_id, not by which process saw it first.
# ---------------------------------------------------------------------------


def test_ra4_cross_node_replay_of_a_leaked_genuine_grant_is_deduplicated():
    ledger = InProcessLedger()
    adapter = CountingAdapter()
    node_a = ExecutionEngine((adapter,), ledger=ledger)
    node_b = ExecutionEngine((adapter,), ledger=ledger)

    grant = grant_for()  # a genuine, valid, unexpired grant
    a = node_a.execute(execution_request(), grant)
    assert a.status is ExecutionStatus.SUCCEEDED

    b = node_b.execute(execution_request(), grant)  # same grant object, other node
    _assert_replayed(b, adapter)


# ---------------------------------------------------------------------------
# execution_id semantics — grant_id is audit only; re-issue replays, a
# policy_version bump is a new execution.
# ---------------------------------------------------------------------------


def test_reissued_genuine_grant_for_same_binding_replays():
    ledger = InProcessLedger()
    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger)

    first = engine.execute(execution_request(), grant_for())
    assert first.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    second_grant = grant_for()  # brand-new grant_id, same policy binding
    second = engine.execute(execution_request(), second_grant)
    _assert_replayed(second, adapter)
    assert second.execution_id == first.execution_id


def test_new_policy_version_is_a_new_execution_id_not_a_replay():
    ledger = InProcessLedger()
    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger)

    first = engine.execute(execution_request(), grant_for(version="1"))
    assert first.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    bumped = engine.execute(execution_request(), grant_for(version="2"))
    assert bumped.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 2
    assert bumped.execution_id != first.execution_id


# ---------------------------------------------------------------------------
# Key rotation must not reset the ledger: a previously completed execution
# still replays after the signing key changes.
# ---------------------------------------------------------------------------


def test_signing_key_rotation_does_not_reset_the_ledger():
    ledger = InProcessLedger()
    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger)

    first = engine.execute(execution_request(), grant_for())
    assert first.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    # Rotate the signing key: a grant issued under the *old* key is now
    # rejected by P4-00D. A grant issued under the *new* key for the same
    # policy binding must still replay, because the ledger dedups on
    # execution_id, not on the key.
    import os

    os.environ["DOR_AUTHORITY_SIGNING_KEY"] = os.urandom(32).hex()
    try:
        new_grant = grant_for()
    finally:
        del os.environ["DOR_AUTHORITY_SIGNING_KEY"]

    second = engine.execute(execution_request(), new_grant)
    _assert_replayed(second, adapter)


# ---------------------------------------------------------------------------
# A failed execution must be cached too: a retry after a genuine failure
# replays the failure rather than re-running the adapter.
# ---------------------------------------------------------------------------


class AlwaysFailingAdapter:
    adapter_id = "failing"
    action = ACTION

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, request, *, dispatch=None):
        self.calls += 1
        raise RuntimeError("downstream unavailable")


def test_failed_execution_is_cached_and_not_retried():
    ledger = InProcessLedger()
    adapter = AlwaysFailingAdapter()
    engine = ExecutionEngine((adapter,), ledger=ledger)

    first = engine.execute(execution_request(), grant_for())
    assert first.status is ExecutionStatus.FAILED
    assert adapter.calls == 1

    second = engine.execute(execution_request(), grant_for())
    assert second.status is ExecutionStatus.REPLAYED
    assert second.output == first.output
    assert adapter.calls == 1


# ---------------------------------------------------------------------------
# No ledger == no durability: the legacy in-memory model must still pass the
# single-process replay contract but cannot pass the durable ones. This test
# documents the pre-P4-01 baseline so the contract is explicit about scope.
# ---------------------------------------------------------------------------


def test_without_ledger_in_process_replay_still_works():
    adapter = CountingAdapter()
    engine = ExecutionEngine((adapter,))  # default in-memory, not durable

    first = engine.execute(execution_request(), grant_for())
    assert first.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    second = engine.execute(execution_request(), grant_for())
    _assert_replayed(second, adapter)


def test_without_ledger_a_restart_replays_the_adapter_unprotected():
    """Baseline: a new engine without a shared ledger re-runs the adapter.

    This is the attack P4-01 closes (RA-1). It is kept as a *negative* control
    proving the attack exists in the pre-ledger model.
    """
    adapter = CountingAdapter()
    first = ExecutionEngine((adapter,)).execute(execution_request(), grant_for())
    assert first.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 1

    restarted = ExecutionEngine((adapter,))  # fresh in-memory store
    second = restarted.execute(execution_request(), grant_for())
    assert second.status is ExecutionStatus.SUCCEEDED
    assert adapter.calls == 2  # <-- the double side effect P4-01 must block
