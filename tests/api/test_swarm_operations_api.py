"""API tests for /api/v1/swarm/ops/* endpoints."""

from __future__ import annotations

import os

os.environ.setdefault("DOR_JWT_SECRET_KEY", "test-secret-key-min-32-chars-long")
os.environ.setdefault("DOR_ENV", "test")
os.environ.setdefault("DOR_ADMIN_USERNAME", "admin")
os.environ.setdefault("DOR_ADMIN_PASSWORD", "admin")

from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


def _auth_token() -> str:
    r = client.post("/auth/token", data={"username": "admin", "password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_auth_token()}"}


def test_ops_endpoints_require_auth():
    for path in (
        "/api/v1/swarm/ops/snapshot",
        "/api/v1/swarm/ops/metrics",
        "/api/v1/swarm/ops/health",
    ):
        r = client.get(path)
        assert r.status_code in (401, 403), f"{path} -> {r.status_code}"


def test_ops_health_ok():
    r = client.get("/api/v1/swarm/ops/health", headers=_auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] in ("ok", "degraded", "down")
    assert "components" in body
    assert isinstance(body["components"], dict)


def test_ops_snapshot_json():
    r = client.get("/api/v1/swarm/ops/snapshot", headers=_auth_header())
    assert r.status_code == 200, r.text
    body = r.json()
    for key in (
        "captured_at",
        "status",
        "queue",
        "workers",
        "dlq",
        "circuit_breakers",
        "performance",
        "cost",
        "components",
    ):
        assert key in body, f"missing {key}"
    assert "depth_by_status" in body["queue"]


def test_ops_metrics_prometheus_text():
    r = client.get("/api/v1/swarm/ops/metrics", headers=_auth_header())
    assert r.status_code == 200, r.text
    assert "text/plain" in r.headers.get("content-type", "")
    text = r.text
    assert "swarm_queue_depth{" in text
    assert "swarm_workers_active" in text
    assert "swarm_dlq_size" in text
