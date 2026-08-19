"""Durable SQLAlchemy replay ledger — RA-1 restart and state machine."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.authority.engine import AuthorityEngine
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.authority.models import AuthorityPolicy, AuthorityRequest, AuthorityRule, Decision
from phase4.execution import (
    AdapterResult,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionStatus,
    StaticExecutionAdapter,
)
from phase4.execution.durable_ledger import (
    ExecutionReplayLedgerModel,
    SqlAlchemyReplayLedger,
)
from phase4.execution.models import ExecutionResult
from phase4.execution.replay_ledger import ClaimOutcomeKind, LedgerStatus


def _make_ledger(url: str = "sqlite:///:memory:") -> tuple[SqlAlchemyReplayLedger, any]:
    engine = create_engine(url, future=True)
    assert ExecutionReplayLedgerModel.__tablename__ == "execution_replay_ledger"
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return SqlAlchemyReplayLedger(sessions), engine


def _result(execution_id: str, status: ExecutionStatus) -> ExecutionResult:
    return ExecutionResult(
        execution_id=execution_id,
        request_id="req-1",
        authority_policy_id="policy-1",
        authority_policy_version="1",
        agent_identity="agent-1",
        action="demo.read",
        resource="object/1",
        context_packet_id="ctx-1",
        status=status,
        adapter_id="adapter-1",
        output=(("ok", "1"),) if status is ExecutionStatus.SUCCEEDED else (),
        error=None if status is ExecutionStatus.SUCCEEDED else "boom",
        executed_at="2026-08-18T00:00:00+00:00",
    )


def test_durable_claim_succeed_and_replay():
    ledger, _ = _make_ledger()
    assert ledger.try_claim("e1").kind is ClaimOutcomeKind.ACQUIRED
    ledger.complete_succeeded("e1", _result("e1", ExecutionStatus.SUCCEEDED))
    again = ledger.try_claim("e1")
    assert again.kind is ClaimOutcomeKind.ALREADY_SUCCEEDED
    assert again.record is not None
    assert again.record.result is not None
    assert again.record.result.status is ExecutionStatus.SUCCEEDED


def test_durable_failed_is_retryable():
    ledger, _ = _make_ledger()
    ledger.try_claim("e1")
    ledger.complete_failed("e1", _result("e1", ExecutionStatus.FAILED))
    assert ledger.get("e1").status is LedgerStatus.FAILED
    assert ledger.try_claim("e1").kind is ClaimOutcomeKind.ACQUIRED


def test_durable_pending_is_in_flight():
    ledger, _ = _make_ledger()
    assert ledger.try_claim("e1").kind is ClaimOutcomeKind.ACQUIRED
    assert ledger.try_claim("e1").kind is ClaimOutcomeKind.IN_FLIGHT


def test_durable_abandon_retains_row():
    ledger, _ = _make_ledger()
    ledger.try_claim("e1")
    ledger.abandon("e1")
    record = ledger.get("e1")
    assert record is not None
    assert record.status is LedgerStatus.ABANDONED
    assert ledger.try_claim("e1").kind is ClaimOutcomeKind.ACQUIRED


def test_survives_process_restart_via_file_db(tmp_path: Path):
    """RA-1: succeeded claim remains after new engine/session on same DB file."""
    db_path = tmp_path / "replay.sqlite"
    url = f"sqlite:///{db_path}"

    ledger1, engine1 = _make_ledger(url)
    calls = {"n": 0}

    def handler(_):
        calls["n"] += 1
        return AdapterResult(output=(("ok", "1"),))

    req = ExecutionRequest(
        request_id="req-restart",
        agent_identity="agent.demo",
        action="demo.read",
        resource="object/1",
        context_packet_id="ctx-1",
    )
    authority_request = AuthorityRequest(
        request_id=req.request_id,
        agent_identity=req.agent_identity,
        action=req.action,
        resource=req.resource,
        context_packet_id=req.context_packet_id,
        requested_at="2026-08-18T00:00:00+00:00",
        parameters=(),
    )
    policy = AuthorityPolicy(
        policy_id="policy.demo",
        version="1",
        rules=(
            AuthorityRule(
                rule_id="r1",
                action=req.action,
                resource_pattern=req.resource,
                effect=Decision.ALLOW,
            ),
        ),
    )
    grant = VerifiedAuthorityGrant.from_decision(
        AuthorityEngine(policy).evaluate(authority_request)
    )

    engine_a = ExecutionEngine(
        (StaticExecutionAdapter("a", "demo.read", handler),),
        ledger=ledger1,
    )
    first = engine_a.execute(req, grant)
    assert first.status is ExecutionStatus.SUCCEEDED
    assert calls["n"] == 1
    engine1.dispose()

    ledger2, engine2 = _make_ledger(url)
    engine_b = ExecutionEngine(
        (StaticExecutionAdapter("b", "demo.read", handler),),
        ledger=ledger2,
    )
    second = engine_b.execute(req, grant)
    assert second.status is ExecutionStatus.REPLAYED
    assert calls["n"] == 1
    engine2.dispose()


def test_complete_without_pending_raises():
    ledger, _ = _make_ledger()
    with pytest.raises(RuntimeError, match="pending"):
        ledger.complete_succeeded("missing", _result("missing", ExecutionStatus.SUCCEEDED))
