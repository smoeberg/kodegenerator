from datetime import datetime, timezone

from infrastructure.runtime.queue import QueueMessageModel
from infrastructure.runtime.settings import RuntimeSettings


def test_production_settings_require_postgres_and_object_storage(monkeypatch):
    monkeypatch.setenv("DOR_ENV", "production")
    settings = RuntimeSettings(
        database_url="sqlite:///./test.db",
        artifact_store_url=None,
        artifact_bucket="test",
        queue_backend="database",
        queue_poll_interval_seconds=1.0,
        queue_lease_seconds=60,
    )
    try:
        settings.validate_production()
    except ValueError as exc:
        assert "PostgreSQL" in str(exc)
    else:
        raise AssertionError("production SQLite must fail closed")


def test_queue_model_has_recovery_fields():
    fields = QueueMessageModel.__table__.columns
    assert "lease_until" in fields
    assert "worker_id" in fields
    assert "attempts" in fields
    assert fields["status"].nullable is False
