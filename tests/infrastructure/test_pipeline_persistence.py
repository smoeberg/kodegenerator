"""Persistence, restart and fencing tests for pipeline Phase 3."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.llm_replay_store import SQLAlchemyLLMReplayStore
from infrastructure.persistence.models import Base
from infrastructure.persistence.pipeline_state_store import (
    PipelineStateConflictError,
    SQLAlchemyPipelineStateStore,
)
from services.governed_llm import GovernedLLMRuntime
from services.llm_replay import LLMCallInProgressError
from tests.services.test_governed_llm import CountingProvider, request


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'phase3.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_pipeline_snapshot_survives_restart(sessions) -> None:
    first = SQLAlchemyPipelineStateStore(sessions, organization_id="org-1")
    first.save({"version": 1, "workflows": {"wf-1": {"state": "testing"}}})

    restarted = SQLAlchemyPipelineStateStore(sessions, organization_id="org-1")
    assert restarted.load()["workflows"]["wf-1"]["state"] == "testing"
    restarted.save({"version": 1, "workflows": {"wf-1": {"state": "released"}}})

    assert (
        SQLAlchemyPipelineStateStore(sessions, organization_id="org-1").load()[
            "workflows"
        ]["wf-1"]["state"]
        == "released"
    )


def test_pipeline_snapshot_rejects_stale_worker(sessions) -> None:
    seed = SQLAlchemyPipelineStateStore(sessions, organization_id="org-1")
    seed.save({"version": 1})
    worker_a = SQLAlchemyPipelineStateStore(sessions, organization_id="org-1")
    worker_b = SQLAlchemyPipelineStateStore(sessions, organization_id="org-1")
    worker_a.load()
    worker_b.load()
    worker_a.save({"version": 2})
    with pytest.raises(PipelineStateConflictError):
        worker_b.save({"version": 3})


def test_llm_result_replays_across_runtime_restart(sessions) -> None:
    first_provider = CountingProvider()
    first = GovernedLLMRuntime(
        first_provider, replay_store=SQLAlchemyLLMReplayStore(sessions)
    )
    assert first.generate(request()).replayed is False

    restarted_provider = CountingProvider()
    restarted = GovernedLLMRuntime(
        restarted_provider, replay_store=SQLAlchemyLLMReplayStore(sessions)
    )
    assert restarted.generate(request()).replayed is True
    assert first_provider.calls == 1
    assert restarted_provider.calls == 0


def test_expired_llm_lease_is_recovered_and_old_fence_is_rejected(sessions) -> None:
    now = datetime(2026, 8, 28, tzinfo=timezone.utc)
    first = SQLAlchemyLLMReplayStore(sessions, lease_seconds=5, clock=lambda: now)
    old = first.claim("org-1", "command-1", "a" * 64)
    later = now + timedelta(seconds=6)
    recovered_store = SQLAlchemyLLMReplayStore(
        sessions, lease_seconds=5, clock=lambda: later
    )
    recovered = recovered_store.claim("org-1", "command-1", "a" * 64)
    assert recovered.fencing_token != old.fencing_token
    with pytest.raises(LLMCallInProgressError, match="stale"):
        first.complete("org-1", "command-1", "a" * 64, old.fencing_token, {}, {})


def test_unexpired_llm_lease_blocks_second_worker(sessions) -> None:
    store = SQLAlchemyLLMReplayStore(sessions, lease_seconds=30)
    store.claim("org-1", "command-1", "a" * 64)
    with pytest.raises(LLMCallInProgressError, match="already in progress"):
        SQLAlchemyLLMReplayStore(sessions, lease_seconds=30).claim(
            "org-1", "command-1", "a" * 64
        )
