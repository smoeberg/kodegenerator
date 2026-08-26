"""Mock fixtures for DOR Controller GUI (Decision Cockpit)."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Any

NOW = datetime.now(timezone.utc)

def _ts(minutes_ago: int = 0) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()

MOCK_PROJECTS: list[dict[str, Any]] = [
    {"project_id": "proj-oauth2-2026", "name": "OAuth2 Auth Service", "description": "Enterprise OAuth2/OIDC with PKCE.", "status": "IN_PROGRESS", "progress_pct": 68, "active_phase": "IMPLEMENTATION", "organization_id": "org-eira-demo", "created_by": "controller.anna", "launched_at": _ts(240), "task_count": 14, "tasks_done": 9, "tasks_blocked": 1, "risk_level": "MEDIUM"},
    {"project_id": "proj-payment-gateway", "name": "Payment Gateway Adapter", "description": "PCI-aware payment gateway.", "status": "PLANNING", "progress_pct": 22, "active_phase": "ARCHITECTURE", "organization_id": "org-eira-demo", "created_by": "controller.anna", "launched_at": _ts(90), "task_count": 8, "tasks_done": 1, "tasks_blocked": 0, "risk_level": "HIGH"},
    {"project_id": "proj-audit-export", "name": "Audit Export Pipeline", "description": "Immutable audit export to S3.", "status": "REVIEW", "progress_pct": 91, "active_phase": "VERIFICATION", "organization_id": "org-eira-demo", "created_by": "controller.bjorn", "launched_at": _ts(480), "task_count": 6, "tasks_done": 5, "tasks_blocked": 0, "risk_level": "LOW"},
]

MOCK_TASK_GRAPH: dict[str, list[dict[str, Any]]] = {
    "proj-oauth2-2026": [
        {"id": "t-01", "name": "Requirements contract", "status": "DONE", "assignee": "PM Agent"},
        {"id": "t-02", "name": "Architecture ADR", "status": "DONE", "assignee": "Architect"},
        {"id": "t-03", "name": "Token endpoint impl", "status": "DONE", "assignee": "Impl Agent"},
        {"id": "t-04", "name": "PKCE flow", "status": "IN_PROGRESS", "assignee": "Impl Agent"},
        {"id": "t-05", "name": "Security review gate", "status": "BLOCKED", "assignee": "Security"},
        {"id": "t-06", "name": "Integration tests", "status": "PENDING", "assignee": "Test Agent"},
    ],
    "proj-payment-gateway": [
        {"id": "t-11", "name": "PCI scope analysis", "status": "DONE", "assignee": "Security"},
        {"id": "t-12", "name": "Gateway adapter design", "status": "IN_PROGRESS", "assignee": "Architect"},
        {"id": "t-13", "name": "Settlement idempotency", "status": "PENDING", "assignee": "Impl Agent"},
    ],
    "proj-audit-export": [
        {"id": "t-21", "name": "Manifest schema", "status": "DONE", "assignee": "Architect"},
        {"id": "t-22", "name": "S3 export worker", "status": "DONE", "assignee": "Impl Agent"},
        {"id": "t-23", "name": "Signature verification", "status": "IN_PROGRESS", "assignee": "Security"},
        {"id": "t-24", "name": "P3-20 verification", "status": "PENDING", "assignee": "Verifier"},
    ],
}

MOCK_DECISIONS: list[dict[str, Any]] = [
    {
        "decision_id": "dec-001", "project_id": "proj-oauth2-2026", "project_name": "OAuth2 Auth Service",
        "title": "Token storage strategy", "status": "HUMAN_REQUIRED", "raised_at": _ts(35),
        "raised_by": "Architect Agent", "risk_score": 72, "recommendation": "A",
        "alternatives": [
            {"id": "A", "label": "Redis + encrypted at rest (recommended)", "pros": ["Low latency", "TTL native"], "cons": ["Extra infra", "Key rotation"], "risk_delta": -10},
            {"id": "B", "label": "Postgres only", "pros": ["No new service"], "cons": ["Higher latency"], "risk_delta": 5},
            {"id": "C", "label": "Stateless JWT only", "pros": ["Simple scale"], "cons": ["Hard revocation"], "risk_delta": 25},
        ],
        "council_votes": {"Architect": "A", "Security": "A", "PM": "B", "Impl Agent": "A"},
        "context_summary": "PKCE almost complete. Security gate blocked until token storage ADR is decided.",
    },
    {
        "decision_id": "dec-002", "project_id": "proj-payment-gateway", "project_name": "Payment Gateway Adapter",
        "title": "PCI scope boundary for adapter process", "status": "HUMAN_REQUIRED", "raised_at": _ts(18),
        "raised_by": "Security Agent", "risk_score": 88, "recommendation": "A",
        "alternatives": [
            {"id": "A", "label": "Isolated PCI zone + tokenization (recommended)", "pros": ["Minimal PCI scope"], "cons": ["Higher cost"], "risk_delta": -30},
            {"id": "B", "label": "In-process adapter", "pros": ["Faster to ship"], "cons": ["Expands PCI scope"], "risk_delta": 40},
        ],
        "council_votes": {"Architect": "A", "Security": "A", "PM": "B", "Impl Agent": "A"},
        "context_summary": "High-risk decision. Security requires isolated zone; PM argues for speed.",
    },
    {
        "decision_id": "dec-003", "project_id": "proj-audit-export", "project_name": "Audit Export Pipeline",
        "title": "Manifest signing algorithm", "status": "HUMAN_REQUIRED", "raised_at": _ts(8),
        "raised_by": "Architect Agent", "risk_score": 35, "recommendation": "A",
        "alternatives": [
            {"id": "A", "label": "Ed25519 detached signatures (recommended)", "pros": ["Fast", "Small keys"], "cons": ["Less ubiquitous than RSA"], "risk_delta": -5},
            {"id": "B", "label": "RSA-PSS 3072", "pros": ["Universal support"], "cons": ["Larger keys"], "risk_delta": 0},
        ],
        "council_votes": {"Architect": "A", "Security": "A", "PM": "A", "Impl Agent": "A"},
        "context_summary": "Near-consensus. Waiting for human confirmation before P3-20 gate.",
    },
]

MOCK_COUNCIL_MESSAGES: list[dict[str, Any]] = [
    {"id": "msg-101", "project_id": "proj-oauth2-2026", "timestamp": _ts(42), "agent": "Architect", "role_icon": "🏗️", "message": "Recommend Redis with encryption at rest for token storage.", "refs": ["ADR-004 draft"]},
    {"id": "msg-102", "project_id": "proj-oauth2-2026", "timestamp": _ts(40), "agent": "Security", "role_icon": "🛡️", "message": "Agree. Stateless JWT-only is a revocation risk.", "refs": ["SEC-policy-3"]},
    {"id": "msg-103", "project_id": "proj-oauth2-2026", "timestamp": _ts(38), "agent": "PM", "role_icon": "📋", "message": "Postgres-only would avoid a new dependency this sprint.", "refs": ["sprint-plan-w34"]},
    {"id": "msg-104", "project_id": "proj-oauth2-2026", "timestamp": _ts(36), "agent": "Impl Agent", "role_icon": "⚙️", "message": "Redis is already in allowlisted adapters.", "refs": ["adapter-redis-1"]},
    {"id": "msg-105", "project_id": "proj-oauth2-2026", "timestamp": _ts(34), "agent": "Architect", "role_icon": "🏗️", "message": "Raising HUMAN_REQUIRED decision dec-001. Council lean: 3x A, 1x B.", "refs": ["dec-001"]},
    {"id": "msg-201", "project_id": "proj-payment-gateway", "timestamp": _ts(20), "agent": "Security", "role_icon": "🛡️", "message": "PCI scope analysis complete. Prefer isolated zone + tokenization.", "refs": ["dec-002"]},
    {"id": "msg-202", "project_id": "proj-payment-gateway", "timestamp": _ts(17), "agent": "PM", "role_icon": "📋", "message": "Isolated zone adds ~2 weeks. Can we ship B with compensating controls?", "refs": ["roadmap-q3"]},
]

MOCK_TRACE_CHAINS: list[dict[str, Any]] = [
    {
        "id": "trace-oauth-token", "label": "Token endpoint → PKCE tests", "project_id": "proj-oauth2-2026",
        "chain": [
            {"step": "Krav", "id": "REQ-auth-12", "summary": "Authorization Code + PKCE.", "status": "APPROVED"},
            {"step": "ADR", "id": "ADR-003", "summary": "OAuth2 flow: Authorization Code with PKCE.", "status": "APPROVED"},
            {"step": "Task", "id": "t-03", "summary": "Token endpoint implementation", "status": "DONE"},
            {"step": "Patch", "id": "patch-a7c82", "summary": "auth/token.py + tests", "status": "APPLIED"},
            {"step": "Test", "id": "test-pkce-flow", "summary": "PKCE happy path + invalid code_verifier", "status": "PASS"},
        ],
    },
    {
        "id": "trace-payment-scope", "label": "PCI scope → pending ADR", "project_id": "proj-payment-gateway",
        "chain": [
            {"step": "Krav", "id": "REQ-pay-03", "summary": "Card data must not be stored in plaintext.", "status": "APPROVED"},
            {"step": "ADR", "id": "ADR-010 (draft)", "summary": "Isolated PCI zone vs in-process adapter.", "status": "DRAFT"},
            {"step": "Task", "id": "t-12", "summary": "Gateway adapter design", "status": "IN_PROGRESS"},
            {"step": "Decision", "id": "dec-002", "summary": "HUMAN_REQUIRED — PCI boundary", "status": "OPEN"},
        ],
    },
    {
        "id": "trace-audit-manifest", "label": "Audit manifest signing", "project_id": "proj-audit-export",
        "chain": [
            {"step": "Krav", "id": "REQ-audit-07", "summary": "Exported manifests must be cryptographically signed.", "status": "APPROVED"},
            {"step": "ADR", "id": "ADR-015", "summary": "Ed25519 detached signatures.", "status": "PENDING_HUMAN"},
            {"step": "Task", "id": "t-23", "summary": "Signature verification", "status": "IN_PROGRESS"},
            {"step": "Decision", "id": "dec-003", "summary": "HUMAN_REQUIRED — signing algorithm", "status": "OPEN"},
        ],
    },
]

def get_mock_projects() -> list[dict[str, Any]]:
    return list(MOCK_PROJECTS)

def get_mock_task_graph(project_id: str) -> list[dict[str, Any]]:
    return list(MOCK_TASK_GRAPH.get(project_id, []))

def get_mock_decisions(status: str | None = "HUMAN_REQUIRED") -> list[dict[str, Any]]:
    if status is None:
        return list(MOCK_DECISIONS)
    return [d for d in MOCK_DECISIONS if d["status"] == status]

def get_mock_council(project_id: str | None = None) -> list[dict[str, Any]]:
    msgs = MOCK_COUNCIL_MESSAGES
    if project_id:
        msgs = [m for m in msgs if m["project_id"] == project_id]
    return sorted(msgs, key=lambda m: m["timestamp"])

def get_mock_traces(project_id: str | None = None) -> list[dict[str, Any]]:
    if project_id:
        return [t for t in MOCK_TRACE_CHAINS if t["project_id"] == project_id]
    return list(MOCK_TRACE_CHAINS)
