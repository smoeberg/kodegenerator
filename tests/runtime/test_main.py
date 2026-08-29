from __future__ import annotations

from runtime import main as runtime_main


class FakeRuntime:
    instances = []

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.booted = False
        self.instances.append(self)

    def boot(self) -> None:
        self.booted = True


def test_runtime_binds_loopback_by_default(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("DOR_HOST", raising=False)
    FakeRuntime.instances.clear()
    monkeypatch.setattr(runtime_main, "DORRuntime", FakeRuntime)
    monkeypatch.setattr(
        runtime_main.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    runtime_main.main()

    assert calls == [{"host": "127.0.0.1", "port": 8000, "log_level": "info"}]
    assert FakeRuntime.instances[0].booted is True


def test_runtime_allows_explicit_container_binding(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("DOR_HOST", "0.0.0.0")
    FakeRuntime.instances.clear()
    monkeypatch.setattr(runtime_main, "DORRuntime", FakeRuntime)
    monkeypatch.setattr(
        runtime_main.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    runtime_main.main()

    assert calls[0]["host"] == "0.0.0.0"


def test_runtime_does_not_start_server_when_migration_fails(monkeypatch) -> None:
    class FailingRuntime(FakeRuntime):
        def boot(self) -> None:
            raise RuntimeError("migration failed")

    calls = []
    monkeypatch.setattr(runtime_main, "DORRuntime", FailingRuntime)
    monkeypatch.setattr(
        runtime_main.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    try:
        runtime_main.main()
    except RuntimeError as exc:
        assert str(exc) == "migration failed"
    else:
        raise AssertionError("startup must fail closed")
    assert calls == []
