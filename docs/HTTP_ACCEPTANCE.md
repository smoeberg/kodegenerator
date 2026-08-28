# Real HTTP pipeline acceptance

`tests/acceptance/test_http_pipeline.py` is the black-box acceptance gate for
the software-factory control plane. It starts a real Uvicorn process on a TCP
port and does not import or call pipeline services from the test process.

The test verifies authentication, readiness, pipeline creation, organization-
scoped status and gates, worker claim/completion, progression to `released`,
process restart, durable restore, and cross-tenant non-disclosure.

Run the gate with:

```bash
pytest -m acceptance tests/acceptance/test_http_pipeline.py
```

The test uses isolated SQLite database and queue files. Production uses the same
HTTP and persistence contracts with the configured PostgreSQL `DATABASE_URL`.
It deliberately supplies deterministic worker results: Docker/GitHub mutations
remain covered by the fenced backend tests and must not run in CI.

## Worker API

```http
POST /pipeline/workers/claim
Authorization: Bearer <token>
Content-Type: application/json

{
  "worker_id": "worker-1",
  "organization_id": "org-acme",
  "capabilities": []
}
```

Completion requires the same authenticated owner and organization:

```http
POST /pipeline/workers/complete
Authorization: Bearer <token>
Content-Type: application/json

{
  "worker_id": "worker-1",
  "organization_id": "org-acme",
  "task_id": "task-...",
  "success": true,
  "result": {"verification": {"passed": true}}
}
```
