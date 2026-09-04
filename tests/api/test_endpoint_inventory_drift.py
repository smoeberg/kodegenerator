"""Drift tests for the mounted DOR API surface."""

from __future__ import annotations

import os

# Development mode intentionally bypasses hardened runtime configuration so
# importing api.main in CI cannot require production secrets or PostgreSQL.
os.environ.setdefault("DOR_ENV", "development")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

from api.endpoint_inventory import build_inventory  # noqa: E402
from api.main import app  # noqa: E402


def test_inventory_is_machine_derived_and_unique() -> None:
    records = build_inventory(app.routes)
    keys = [(record.path, record.method) for record in records]

    assert records
    assert len(keys) == len(set(keys))
    assert any(record.method == "WEBSOCKET" for record in records)
    assert any(record.path == "/api/v1/execution/ws/{workflow_id}" for record in records)
    assert any(record.path == "/api/v1/execution/events/{workflow_id}" for record in records)


def test_bot_evidence_contract_contains_nine_routes() -> None:
    records = [
        record
        for record in build_inventory(app.routes)
        if record.path.startswith("/api/v1/bot-evidence/")
    ]
    assert len(records) == 9
    assert {record.path for record in records} >= {
        "/api/v1/bot-evidence/evaluations/{evaluation_id}",
        "/api/v1/bot-evidence/rubrics/{rubric_id}/{version}",
        "/api/v1/bot-evidence/observations/{observation_id}",
        "/api/v1/bot-evidence/snapshots/{snapshot_id}",
        "/api/v1/bot-evidence/work-packages/{package_id}",
        "/api/v1/bot-evidence/candidates/{candidate_id}",
        "/api/v1/bot-evidence/candidate-selections/{selection_id}",
        "/api/v1/bot-evidence/integration-plans/{plan_id}",
        "/api/v1/bot-evidence/integration-receipts/{plan_fingerprint}",
    }
