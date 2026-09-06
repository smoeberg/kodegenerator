from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.auth import User, UserInDB
from api.endpoints import execution_realtime
from services.jwt_keyring import JWTKeyRejectedError


def _stored_user(*, credential_version: int = 1) -> UserInDB:
    return UserInDB(
        username="alice",
        organization_id="org-a",
        hashed_password="unused",
        credential_version=credential_version,
    )


class _AcceptingKeyRing:
    def verification_key(self, key_id):
        assert key_id == "legacy"
        return "key"


def test_stream_session_is_scoped_to_workflow_user_credential_and_key(monkeypatch):
    stored = _stored_user()
    monkeypatch.setattr(
        execution_realtime, "get_configured_user", lambda username: stored
    )
    monkeypatch.setattr(
        execution_realtime.JWTKeyRing,
        "from_environment",
        lambda **kwargs: _AcceptingKeyRing(),
    )
    user = User(username="alice", organization_id="org-a")
    token, expires_at = execution_realtime._create_session(
        "wf-1", user, jwt_key_id="legacy"
    )

    resolved = execution_realtime._resolve_session(token, "wf-1")
    assert resolved is not None
    assert resolved.username == "alice"
    assert execution_realtime._resolve_session(token, "wf-2") is None
    assert expires_at > datetime.now(timezone.utc)


def test_expired_stream_session_is_rejected(monkeypatch):
    stored = _stored_user()
    monkeypatch.setattr(
        execution_realtime, "get_configured_user", lambda username: stored
    )
    monkeypatch.setattr(
        execution_realtime.JWTKeyRing,
        "from_environment",
        lambda **kwargs: _AcceptingKeyRing(),
    )
    token, _ = execution_realtime._create_session(
        "wf-1", User(username="alice", organization_id="org-a"), jwt_key_id="legacy"
    )
    execution_realtime._STREAM_SESSIONS[
        execution_realtime._session_digest(token)
    ]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)

    assert execution_realtime._resolve_session(token, "wf-1") is None


def test_stream_session_is_rejected_after_credential_rotation(monkeypatch):
    principal = {"user": _stored_user(credential_version=1)}
    monkeypatch.setattr(
        execution_realtime,
        "get_configured_user",
        lambda username: principal["user"],
    )
    monkeypatch.setattr(
        execution_realtime.JWTKeyRing,
        "from_environment",
        lambda **kwargs: _AcceptingKeyRing(),
    )
    token, _ = execution_realtime._create_session(
        "wf-1", User(username="alice", organization_id="org-a"), jwt_key_id="legacy"
    )

    principal["user"] = _stored_user(credential_version=2)
    assert execution_realtime._resolve_session(token, "wf-1") is None


def test_stream_session_is_rejected_after_signing_key_revocation(monkeypatch):
    stored = _stored_user()
    monkeypatch.setattr(
        execution_realtime, "get_configured_user", lambda username: stored
    )
    monkeypatch.setattr(
        execution_realtime.JWTKeyRing,
        "from_environment",
        lambda **kwargs: _AcceptingKeyRing(),
    )
    token, _ = execution_realtime._create_session(
        "wf-1", User(username="alice", organization_id="org-a"), jwt_key_id="legacy"
    )

    class RevokedKeyRing:
        def verification_key(self, key_id):
            raise JWTKeyRejectedError("revoked")

    monkeypatch.setattr(
        execution_realtime.JWTKeyRing,
        "from_environment",
        lambda **kwargs: RevokedKeyRing(),
    )
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
    monkeypatch.setattr(
        execution_realtime, "_orchestrator", lambda _dor, _user: orchestrator
    )
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
    monkeypatch.setattr(
        execution_realtime, "_orchestrator", lambda _dor, _user: orchestrator
    )
    monkeypatch.setattr(
        execution_realtime,
        "_workflow_project_id",
        lambda value: value.context["project_id"],
    )

    resolved_workflow, project_id = execution_realtime._authorize_workflow(
        SimpleNamespace(), "wf-1", User(username="alice", organization_id="org-a")
    )

    assert resolved_workflow is workflow
    assert project_id == "project-7"
