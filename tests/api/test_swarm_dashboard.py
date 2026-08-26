"""Tests for dashboard API contracts and static web assets."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.endpoints.swarm_dashboard import router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_summary_endpoint_has_dashboard_shape() -> None:
    payload = client().get("/api/v1/swarm/dashboard/summary").json()
    assert payload["active_workers"] == 0
    assert set(payload["queue"]) == {"pending", "active", "dlq"}
    assert "cost" in payload


def test_summary_provider_is_used() -> None:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides = {}
    response = client().get("/api/v1/swarm/dashboard/summary")
    assert response.status_code == 200


def test_events_endpoint_is_sse() -> None:
    response = client().get("/api/v1/swarm/dashboard/events", timeout=0.1)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")


def test_html_contains_required_dashboard_views() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    for view in ("Overview", "Projects", "Workers", "Queue", "Approvals", "Cost &amp; Tokens"):
        assert view in html
    assert "/web/app.js" in html


def test_static_assets_have_no_external_cdn() -> None:
    html = Path("web/index.html").read_text(encoding="utf-8")
    js = Path("web/app.js").read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "http://" not in js and "https://" not in js
