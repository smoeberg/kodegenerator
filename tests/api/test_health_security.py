"""Security regression tests for health and production startup behavior."""

from contextlib import contextmanager

import pytest

from api import main as api_main


@pytest.mark.asyncio
async def test_readiness_does_not_disclose_database_exception(
    monkeypatch, caplog
) -> None:
    class FailingDatabase:
        @contextmanager
        def session(self):
            raise RuntimeError("postgresql://admin:secret@internal-db/dor")
            yield

    monkeypatch.setattr(api_main, "_db", FailingDatabase())

    response = await api_main.health_ready()

    assert response.status_code == 503
    assert response.body == b'{"status":"error","database":"error"}'
    assert "secret" not in str(response)
    assert "readiness database check failed" in caplog.text


def test_production_requires_admin_password(monkeypatch) -> None:
    monkeypatch.setattr(api_main, "IS_PRODUCTION", True)
    monkeypatch.setenv("DOR_JWT_SECRET_KEY", "configured")
    monkeypatch.delenv("DOR_ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="DOR_ADMIN_PASSWORD"):
        api_main.validate_production_security_configuration()
