from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints import auth as auth_endpoint
from api.endpoints import swarm_operations
from services.login_rate_limiter import LoginRateLimiter


def test_login_limiter_applies_pair_backoff_before_expensive_work() -> None:
    now = {"value": 100.0}
    limiter = LoginRateLimiter(
        window_seconds=60,
        ip_limit=10,
        username_limit=10,
        pair_limit=2,
        base_backoff_seconds=2,
        max_backoff_seconds=30,
        clock=lambda: now["value"],
    )

    assert limiter.record_failure("10.0.0.1", "Alice") == 0
    assert limiter.record_failure("10.0.0.1", "alice") == 2
    assert limiter.retry_after("10.0.0.1", "ALICE") == 2

    now["value"] += 2.1
    assert limiter.retry_after("10.0.0.1", "alice") == 0
    assert limiter.record_failure("10.0.0.1", "alice") == 4


def test_success_clears_identity_buckets_but_not_ip_bucket() -> None:
    now = {"value": 100.0}
    limiter = LoginRateLimiter(
        window_seconds=60,
        ip_limit=2,
        username_limit=10,
        pair_limit=10,
        base_backoff_seconds=3,
        max_backoff_seconds=30,
        clock=lambda: now["value"],
    )
    limiter.record_failure("10.0.0.1", "alice")
    assert limiter.record_failure("10.0.0.1", "bob") == 3

    limiter.record_success("10.0.0.1", "alice")
    assert limiter.retry_after("10.0.0.1", "alice") == 3


@pytest.mark.asyncio
async def test_blocked_login_does_not_verify_password_or_seed_runtime(monkeypatch) -> None:
    limiter = MagicMock()
    limiter.retry_after.return_value = 9
    authenticate = MagicMock()
    seed = MagicMock()
    monkeypatch.setattr(auth_endpoint, "_login_rate_limiter", limiter)
    monkeypatch.setattr(auth_endpoint, "authenticate_configured_user", authenticate)
    monkeypatch.setattr(auth_endpoint, "ensure_bootstrap_runtime_context", seed)

    request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.9"))
    form = SimpleNamespace(username="admin", password="wrong")
    with pytest.raises(HTTPException) as exc_info:
        await auth_endpoint.login_for_access_token(request, form)

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "9"
    authenticate.assert_not_called()
    seed.assert_not_called()


@pytest.mark.asyncio
async def test_failed_password_does_not_seed_runtime(monkeypatch) -> None:
    limiter = MagicMock()
    limiter.retry_after.return_value = 0
    limiter.record_failure.return_value = 0
    seed = MagicMock()
    monkeypatch.setattr(auth_endpoint, "_login_rate_limiter", limiter)
    monkeypatch.setattr(
        auth_endpoint, "authenticate_configured_user", lambda username, password: None
    )
    monkeypatch.setattr(auth_endpoint, "ensure_bootstrap_runtime_context", seed)

    request = SimpleNamespace(client=SimpleNamespace(host="10.0.0.9"))
    form = SimpleNamespace(username="admin", password="wrong")
    with pytest.raises(HTTPException) as exc_info:
        await auth_endpoint.login_for_access_token(request, form)

    assert exc_info.value.status_code == 401
    seed.assert_not_called()


class _Database:
    def __init__(self, membership) -> None:
        self.membership = membership

    @contextmanager
    def session(self):
        yield SimpleNamespace(get=lambda model, key: self.membership)


def _dor_with_membership(*, is_admin: bool):
    return SimpleNamespace(database=_Database(SimpleNamespace(is_admin=is_admin)))


def test_global_metrics_reject_regular_tenant_admin(monkeypatch) -> None:
    monkeypatch.setenv("DOR_OPERATOR_USERNAME", "platform-admin")
    monkeypatch.setenv("DOR_OPERATOR_ORGANIZATION_ID", "platform-org")
    tenant_admin = User(username="tenant-admin", organization_id="tenant-org")

    with pytest.raises(HTTPException) as exc_info:
        swarm_operations._require_platform_operator(
            tenant_admin, _dor_with_membership(is_admin=True)
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == {"error": "platform_operator_required"}


def test_global_metrics_require_operator_admin_membership(monkeypatch) -> None:
    monkeypatch.setenv("DOR_OPERATOR_USERNAME", "platform-admin")
    monkeypatch.setenv("DOR_OPERATOR_ORGANIZATION_ID", "platform-org")
    operator = User(username="platform-admin", organization_id="platform-org")

    with pytest.raises(HTTPException):
        swarm_operations._require_platform_operator(
            operator, _dor_with_membership(is_admin=False)
        )

    assert (
        swarm_operations._require_platform_operator(
            operator, _dor_with_membership(is_admin=True)
        )
        is operator
    )
