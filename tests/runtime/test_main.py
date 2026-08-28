from __future__ import annotations

from runtime import main as runtime_main


class FakeDatabase:
    def create_all(self) -> None:
        pass


def test_runtime_binds_loopback_by_default(monkeypatch) -> None:
    calls = []
    monkeypatch.delenv("DOR_HOST", raising=False)
    monkeypatch.setattr(runtime_main, "Database", FakeDatabase)
    monkeypatch.setattr(
        runtime_main.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    runtime_main.main()

    assert calls == [{"host": "127.0.0.1", "port": 8000, "log_level": "info"}]


def test_runtime_allows_explicit_container_binding(monkeypatch) -> None:
    calls = []
    monkeypatch.setenv("DOR_HOST", "0.0.0.0")
    monkeypatch.setattr(runtime_main, "Database", FakeDatabase)
    monkeypatch.setattr(
        runtime_main.uvicorn, "run", lambda *args, **kwargs: calls.append(kwargs)
    )

    runtime_main.main()

    assert calls[0]["host"] == "0.0.0.0"
