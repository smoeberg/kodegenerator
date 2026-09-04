from sqlalchemy import inspect

from runtime.core import DORRuntime


def test_runtime_boot_preserves_explicit_database_url_over_environment(
    tmp_path, monkeypatch
) -> None:
    ambient_database = tmp_path / "ambient.db"
    runtime_database = tmp_path / "runtime.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{ambient_database}")

    runtime = DORRuntime(f"sqlite:///{runtime_database}")
    runtime.boot()

    tables = set(inspect(runtime.database.engine).get_table_names())
    assert "organizations" in tables
    assert runtime_database.exists()
    assert not ambient_database.exists()
