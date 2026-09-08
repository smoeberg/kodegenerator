from __future__ import annotations

import os

from scripts import worker_healthcheck


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement):
        return None


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def connect(self):
        return _Connection()

    def dispose(self) -> None:
        self.disposed = True


def test_healthcheck_materializes_runtime_secrets_before_database_probe(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    calls: list[str] = []
    engine = _Engine()

    def materialize() -> None:
        calls.append("materialize")
        os.environ["DATABASE_URL"] = "postgresql+psycopg://dor:secret@postgres:5432/dor"

    def create_engine(database_url: str, *, pool_pre_ping: bool):
        calls.append("create_engine")
        assert database_url == os.environ["DATABASE_URL"]
        assert pool_pre_ping is True
        return engine

    monkeypatch.setattr(worker_healthcheck, "materialize_runtime_secrets", materialize)
    monkeypatch.setattr(
        worker_healthcheck.Path,
        "read_bytes",
        lambda self: b"python\x00-m\x00services.worker_agent\x00",
    )
    monkeypatch.setattr(worker_healthcheck, "create_engine", create_engine)

    worker_healthcheck.main()

    assert calls == ["materialize", "create_engine"]
    assert engine.disposed is True
