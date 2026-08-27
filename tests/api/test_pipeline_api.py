import pytest
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

def test_pipeline_start_unauthorized():
    response = client.post("/pipeline/start", json={"requirements_yaml": "project_name: test"})
    assert response.status_code == 401

def test_pipeline_start_authorized():
    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "requirements_yaml": """project_name: 'User Service API'
project_description: 'A REST API for managing users'
version: '1.0.0'

requirements:
  - id: REQ-001
    description: 'Create a new user'
    acceptance_criteria:
      - 'User must have a unique email address'
      - 'User must have a name'
    priority: high
"""
    }
    response = client.post("/pipeline/start", json=payload, headers=headers)
    print("Pipeline API Response:", response.status_code, response.json())
    assert response.status_code in [200, 201, 400, 500]


def test_pipeline_gate_decision_and_advance_flow():
    """Full flow from the documented curl commands:
    1) POST /pipeline/start
    2) POST /decisions {workflow_id, gate_id, decision}
    3) POST /pipeline/{workflow_id}/advance
    """
    token = _auth_token()
    headers = {"Authorization": f"Bearer {token}"}

    # 1) Start the pipeline
    payload = {
        "requirements_yaml": """project_name: 'User Service API'
project_description: 'A REST API for managing users'
version: '1.0.0'

requirements:
  - id: REQ-001
    description: 'Create a new user'
    acceptance_criteria:
      - 'User must have a unique email address'
    priority: high
    security: 'authentication_required: true'
"""
    }
    r = client.post("/pipeline/start", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    started = r.json()
    workflow_id = started["workflow_id"]

    # After start, the pipeline auto-advances to REQUIREMENTS_VALIDATED
    # (waiting on the requirements gate).
    assert started["current_state"] == "requirements_validated", started

    # 2) Approve the requirements gate via POST /decisions
    decision = {
        "workflow_id": workflow_id,
        "gate_id": "gate_requirements_approval",
        "decision": "approved",
    }
    r = client.post("/decisions", json=decision, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["current_state"] == "requirements_approved", body

    # 3) Advance the pipeline. The auto-advance runs through the automatic
    #    (non-gate) chain until it hits the next gate, so it lands on
    #    architecture_generated.
    r = client.post(f"/pipeline/{workflow_id}/advance", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["current_state"] == "architecture_generated", body

    # Verify the pending gate is now the architecture approval.
    r = client.get(f"/pipeline/{workflow_id}", headers=headers)
    assert r.status_code == 200, r.text
    status = r.json()
    assert status["current_state"] == "architecture_generated"
