"""Engine-level lease reclaim (RA-3) and concurrent reclaim race."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from phase4.authority.engine import AuthorityEngine
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import (
    AuthorityDecision,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)
from phase4.execution import (
    AdapterResult,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionStatus,
    InMemoryReplayLedger,
    StaticExecutionAdapter,
    execution_id_for,
)
from phase4.execution.replay_ledger import ClaimOutcomeKind, LedgerStatus


def _request() -> ExecutionRequest:
    return ExecutionRequest(
        request_id="req-lease-engine",
        agent_identity="agent.demo",
        action="demo.read",
        resource="object/1",
        context_packet_id="ctx-1",
        parameters=(("k", "v"),),
    )


def _grant(req: ExecutionRequest) -> VerifiedAuthorityGrant:
    authority_request = AuthorityRequest(
        request_id=req.request_id,
        agent_identity=req.agent_identity,
        action=req.action,
        resource=req.resource,
        context_packet_id=req.context_packet_id,
        requested_at="2026-08-18T00:00:00+00:00",
        parameters=req.parameters,
    )
    policy = AuthorityPolicy(
        policy_id="policy.demo",
        version="1",
        rules=(
            AuthorityRule(
                rule_id="rule.allow",
                action=req.action,
                resource_pattern=req.resource,
                effect=Decision.ALLOW,
            ),
        ),
    )
    return VerifiedAuthorityGrant.from_decision(
        AuthorityEngine(policy).evaluate(authority_request)
    )


def _decision_for_id(req: ExecutionRequest, grant: VerifiedAuthorityGrant) -> AuthorityDecision:
    return AuthorityDecision(
        request_id=grant.request_id,
        decision=Decision.ALLOW,
        agent_identity=grant.agent_identity,
        action=grant.action,
        resource=grant.resource,
        context_packet_id=grant.context_packet_id,
        policy_id=grant.policy_id,
        policy_version=grant.policy_version,
        matched_rule_ids=grant.matched_rule_ids,
        reason="test",
        evaluated_at="test",
        parameters=grant.parameters,
        organization_id=grant.organization_id,
        actor_id=grant.actor_id,
        capability=grant.capability,
    )


def test_engine_rejects_second_call_while_pending_within_lease():
    """Active lease → second execute is REJECTED in-flight, adapter not double-run."""
    ledger = InMemoryReplayLedger(claim_lease_seconds=120)
    req = _request()
    grant = _grant(req)
    eid = execution_id_for(req, _decision_for_id(req, grant))

    # Simulate worker that claimed but has not completed yet
    assert ledger.try_claim(eid).kind is ClaimOutcomeKind.ACQUIRED

    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    engine = ExecutionEngine(
        (StaticExecutionAdapter("a", "demo.read", handler),),
        ledger=ledger,
    )
    result = engine.execute(req, grant)
    assert result.status is ExecutionStatus.REJECTED
    assert "in flight" in (result.error or "").lower()
    assert calls["n"] == 0


def test_engine_reclaims_after_lease_expiry_and_runs_adapter_once():
    """RA-3: expired pending claim is reclaimed; adapter runs once then REPLAYED."""
    lease = 30
    ledger = InMemoryReplayLedger(claim_lease_seconds=lease)
    req = _request()
    grant = _grant(req)
    decision = _decision_for_id(req, grant)
    eid = execution_id_for(req, decision)

    # Crash-shaped pending: claimed in the past, never completed
    past = datetime.now(timezone.utc) - timedelta(seconds=lease + 5)
    seeded = ledger.try_claim(eid, now=past)
    assert seeded.kind is ClaimOutcomeKind.ACQUIRED
    assert ledger.get(eid).status is LedgerStatus.PENDING

    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    engine = ExecutionEngine(
        (StaticExecutionAdapter("a", "demo.read", handler),),
        ledger=ledger,
    )
    first = engine.execute(req, grant)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert calls["n"] == 1

    second = engine.execute(req, grant)
    assert second.status is ExecutionStatus.REPLAYED
    assert calls["n"] == 1


def test_concurrent_reclaim_of_expired_pending_single_winner():
    """Race: many try_claim on expired pending → exactly one ACQUIRED."""
    lease = 10
    ledger = InMemoryReplayLedger(claim_lease_seconds=lease)
    past = datetime.now(timezone.utc) - timedelta(seconds=lease + 2)
    assert ledger.try_claim("race-id", now=past).kind is ClaimOutcomeKind.ACQUIRED

    outcomes: list[ClaimOutcomeKind] = []

    def attempt() -> ClaimOutcomeKind:
        return ledger.try_claim("race-id").kind

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(attempt) for _ in range(16)]
        for fut in as_completed(futures):
            outcomes.append(fut.result())

    assert outcomes.count(ClaimOutcomeKind.ACQUIRED) == 1
    assert outcomes.count(ClaimOutcomeKind.IN_FLIGHT) == 15
    assert ledger.get("race-id").status is LedgerStatus.PENDING


def test_concurrent_engine_execute_after_expired_seed_single_adapter_call():
    """Two engines race after expired seed → one SUCCEEDED, one REPLAYED or REJECTED."""
    lease = 15
    ledger = InMemoryReplayLedger(claim_lease_seconds=lease)
    req = _request()
    grant = _grant(req)
    eid = execution_id_for(req, _decision_for_id(req, grant))
    past = datetime.now(timezone.utc) - timedelta(seconds=lease + 3)
    assert ledger.try_claim(eid, now=past).kind is ClaimOutcomeKind.ACQUIRED

    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    def run() -> ExecutionStatus:
        engine = ExecutionEngine(
            (StaticExecutionAdapter("a", "demo.read", handler),),
            ledger=ledger,
        )
        return engine.execute(req, grant).status

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = [f.result() for f in as_completed([pool.submit(run), pool.submit(run)])]

    assert calls["n"] == 1
    assert ExecutionStatus.SUCCEEDED in statuses
    # Loser is either REPLAYED (winner finished) or REJECTED in-flight (winner still pending)
    assert set(statuses) <= {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.REPLAYED,
        ExecutionStatus.REJECTED,
    }
    assert statuses.count(ExecutionStatus.SUCCEEDED) == 1
