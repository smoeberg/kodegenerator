from __future__ import annotations

import hashlib
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.authority import (
    AuthorityEngine,
    AuthorityPolicy,
    AuthorityRequest,
    AuthorityRule,
    Decision,
)
from phase4.authority.grants import VerifiedAuthorityGrant
from phase4.execution import (
    AdapterResult,
    ExecutionEngine,
    ExecutionRequest,
    ExecutionStatus,
    SqlAlchemyReplayLedger,
    StaticExecutionAdapter,
)
from phase4.execution.replay_ledger import InMemoryReplayLedger
from phase4.implementation_agent.patch_adapter import (
    StaleBaselineConflictError,
    atomic_write_if_hash_matches,
)
from phase6.execution.process import BubblewrapProcessAdapter
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionOutcome,
    ExecutionSecurityContext,
    ExecutionSpec,
)
from services.llm_adapters import MockLLMAdapter, SchemaValidationError


def test_sandbox_cannot_read_sensitive_host_files(tmp_path: Path) -> None:
    bubblewrap = shutil.which("bwrap")
    if bubblewrap is None:
        pytest.skip("bubblewrap is not installed")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = tmp_path / "host-secret"
    secret.write_text("must-not-leak", encoding="utf-8")
    script = workspace / "probe.py"
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(secret)!r}).read_text(encoding='utf-8')\n",
        encoding="utf-8",
    )
    python = "/usr/bin/python3" if Path("/usr/bin/python3").exists() else str(Path(sys.executable).resolve())
    adapter = BubblewrapProcessAdapter(allowed_executables=(python,), bubblewrap_path=bubblewrap)
    result = adapter.execute(
        ExecutionSpec(
            execution_id="sandbox-secret-probe",
            adapter_id=adapter.adapter_id,
            argv=(python, str(script)),
            security=ExecutionSecurityContext("org-security", "principal-security", "actor-security"),
            limits=ExecutionLimits(wall_time_seconds=5, cpu_time_seconds=2, memory_bytes=128 * 1024 * 1024),
            writable_paths=(str(workspace),),
            working_directory=str(workspace),
        )
    )
    if result.output.startswith("bwrap:") and "FileNotFoundError" not in result.output:
        pytest.skip(f"bubblewrap namespaces are unavailable: {result.output.strip()}")
    assert result.outcome is ExecutionOutcome.FAILED
    assert "FileNotFoundError" in result.output or "PermissionError" in result.output
    assert "must-not-leak" not in result.output


def test_concurrent_worker_cannot_overwrite_live_changes(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    original = b"VERSION = 1\n"
    target.write_bytes(original)
    expected = hashlib.sha256(original).hexdigest()
    barrier = Barrier(2)
    outcomes: list[str] = []
    outcomes_lock = Lock()

    def worker(content: bytes) -> None:
        barrier.wait()
        try:
            atomic_write_if_hash_matches(target, content, expected)
            outcome = "committed"
        except StaleBaselineConflictError:
            outcome = "stale"
        with outcomes_lock:
            outcomes.append(outcome)

    candidates = (b"VERSION = 2\n", b"VERSION = 3\n")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, candidate) for candidate in candidates]
        for future in futures:
            future.result(timeout=5)

    assert sorted(outcomes) == ["committed", "stale"]
    assert target.read_bytes() in candidates


def _grant_for(request: ExecutionRequest) -> VerifiedAuthorityGrant:
    policy = AuthorityPolicy(
        policy_id="policy.security-replay",
        version="1",
        rules=(AuthorityRule(rule_id="allow", action=request.action, resource_pattern=request.resource, effect=Decision.ALLOW),),
    )
    decision = AuthorityEngine(policy).evaluate(
        AuthorityRequest(
            request_id=request.request_id,
            agent_identity=request.agent_identity,
            action=request.action,
            resource=request.resource,
            context_packet_id=request.context_packet_id,
            requested_at="2026-08-27T09:31:00+00:00",
            parameters=request.parameters,
            organization_id=request.organization_id,
        )
    )
    return VerifiedAuthorityGrant.from_decision(decision)


def test_execution_state_survives_process_restart(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'replay.db'}"
    database_a = create_engine(database_url)
    Base.metadata.create_all(database_a)
    sessions_a = sessionmaker(bind=database_a, expire_on_commit=False)
    calls = 0

    def side_effect(_request: ExecutionRequest) -> AdapterResult:
        nonlocal calls
        calls += 1
        return AdapterResult(output=(("commit", "deadbeef"),))

    request = ExecutionRequest.create(
        request_id="request-restart",
        agent_identity="agent.implementation",
        action="repository.commit",
        resource="repo:legacy",
        context_packet_id="context-restart",
        organization_id="org-security",
        idempotency_key="restart-safe-command",
    )
    first_engine = ExecutionEngine(
        (StaticExecutionAdapter("adapter.commit.first", request.action, side_effect),),
        ledger=SqlAlchemyReplayLedger(
            sessions_a, organization_id="org-security"
        ),
    )
    first = first_engine.execute(request, _grant_for(request))
    assert first.status is ExecutionStatus.SUCCEEDED
    database_a.dispose()

    database_b = create_engine(database_url)
    sessions_b = sessionmaker(bind=database_b, expire_on_commit=False)
    restarted_engine = ExecutionEngine(
        (StaticExecutionAdapter("adapter.commit.restarted", request.action, side_effect),),
        ledger=SqlAlchemyReplayLedger(
            sessions_b, organization_id="org-security"
        ),
    )
    replay = restarted_engine.execute(request, _grant_for(request))
    database_b.dispose()

    assert replay.status is ExecutionStatus.REPLAYED
    assert replay.output == first.output
    assert calls == 1


def test_llm_adapter_fails_closed_on_invalid_schema() -> None:
    schema = {
        "type": "object",
        "properties": {"approved": {"type": "boolean"}},
        "required": ["approved"],
        "additionalProperties": False,
    }
    with pytest.raises(SchemaValidationError):
        MockLLMAdapter('{"approved":"yes"}').generate("approve this change", schema=schema)


def test_production_rejects_in_memory_replay_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOR_ENV", "production")
    with pytest.raises(RuntimeError, match="durable execution replay ledger"):
        ExecutionEngine()
    with pytest.raises(RuntimeError, match="durable execution replay ledger"):
        ExecutionEngine(ledger=InMemoryReplayLedger())
