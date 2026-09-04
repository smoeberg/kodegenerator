from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.auth import User
from api.endpoints import execution_realtime


def test_stream_session_is_scoped_to_workflow_and_user(monkeypatch):
    user = User(username="alice", organization_id="org-a")
    token, expires_at = execution_realtime._create_session("wf-1", user)

    monkeypatch.setattr(execution_realtime, "get_configured_user", lambda username: user)

    resolved = execution_realtime._resolve_session(token, "wf-1")
    assert resolved is not None
    assert resolved.username == "alice"
    assert execution_realtime._resolve_session(token, "wf-2") is None
    assert expires_at > datetime.now(timezone.utc)


def test_expired_stream_session_is_rejected(monkeypatch):
    user = User(username="alice", organization_id="org-a")
    token, _ = execution_realtime._create_session("wf-1", user)
    execution_realtime._STREAM_SESSIONS[execution_realtime._session_digest(token)]["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    )
    monkeypatch.setattr(execution_realtime, "get_configured_user", lambda username: user)

    assert execution_realtime._resolve_session(token, "wf-1") is None


def test_workflow_authorization_rejects_cross_tenant_access():
    workflow = SimpleNamespace(
        id="wf-1",
        context={"organization_id": "org-a"},
        metadata={},
    )
    orchestrator = SimpleNamespace(_get_workflow=lambda workflow_id: workflow)
    dor = SimpleNamespace()
    user = User(username="bob", organization_id="org-b")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(execution_realtime, "_orchestrator", lambda _dor: orchestrator)
    try:
        with pytest.raises(HTTPException) as exc_info:
            execution_realtime._authorize_workflow(dor, "wf-1", user)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail == "Execution access denied"
    finally:
        monkeypatch.undo()


def test_workflow_authorization_uses_canonical_project_identity(monkeypatch):
    workflow = SimpleNamespace(
        id="wf-1",
        context={"organization_id": "org-a", "project_id": "project-7"},
        metadata={},
    )
    orchestrator = SimpleNamespace(_get_workflow=lambda workflow_id: workflow)
    monkeypatch.setattr(execution_realtime, "_orchestrator", lambda _dor: orchestrator)
    monkeypatch.setattr(execution_realtime, "_workflow_project_id", lambda value: value.context["project_id"])

    resolved_workflow, project_id = execution_realtime._authorize_workflow(
        SimpleNamespace(), "wf-1", User(username="alice", organization_id="org-a")
    )

    assert resolved_workflow is workflow
    assert project_id == "project-7"
