"""Persistent identity boundary and token invalidation tests."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api.auth as auth
from infrastructure.persistence.models import Base
from services.identity_store import IdentityStore


def _stores(tmp_path):
    database = tmp_path / "identity.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return IdentityStore(sessions), IdentityStore(sessions), database


def test_identity_is_shared_between_api_instances(tmp_path) -> None:
    first, second, _ = _stores(tmp_path)
    first.create_if_absent(
        username="Operator",
        hashed_password=auth.get_password_hash("correct horse battery staple"),
        organization_id="org-a",
    )

    persisted = second.get("operator")

    assert persisted is not None
    assert persisted["username"] == "operator"
    assert persisted["organization_id"] == "org-a"
    assert auth.verify_password(
        "correct horse battery staple", persisted["hashed_password"]
    )


def test_password_rotation_invalidates_existing_token(tmp_path, monkeypatch) -> None:
    first, _, database = _stores(tmp_path)
    first.create_if_absent(
        username="operator",
        hashed_password=auth.get_password_hash("initial-password"),
    )
    monkeypatch.setenv("DOR_IDENTITY_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setattr(auth, "_identity_store", None)
    monkeypatch.setattr(auth, "_identity_store_url", None)
    token = auth.create_access_token({"sub": "operator", "cv": 1})
    assert auth.authenticate_access_token(token).username == "operator"

    first.rotate_password("operator", auth.get_password_hash("replacement-password"))

    with pytest.raises(HTTPException) as exc_info:
        auth.authenticate_access_token(token)
    assert exc_info.value.status_code == 401


def test_disabled_principal_is_rejected_immediately(tmp_path, monkeypatch) -> None:
    store, _, database = _stores(tmp_path)
    store.create_if_absent(
        username="operator",
        hashed_password=auth.get_password_hash("initial-password"),
    )
    monkeypatch.setenv("DOR_IDENTITY_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setattr(auth, "_identity_store", None)
    monkeypatch.setattr(auth, "_identity_store_url", None)
    token = auth.create_access_token({"sub": "operator", "cv": 1})
    store.set_disabled("operator", True)

    with pytest.raises(HTTPException) as exc_info:
        auth.authenticate_access_token(token)
    assert exc_info.value.status_code == 401


def test_token_organization_must_match_persisted_identity(
    tmp_path, monkeypatch
) -> None:
    store, _, database = _stores(tmp_path)
    store.create_if_absent(
        username="operator",
        hashed_password=auth.get_password_hash("initial-password"),
        organization_id="org-a",
    )
    monkeypatch.setenv("DOR_IDENTITY_DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setattr(auth, "_identity_store", None)
    monkeypatch.setattr(auth, "_identity_store_url", None)

    valid = auth.create_access_token({"sub": "operator", "cv": 1, "org": "org-a"})
    assert auth.authenticate_access_token(valid).organization_id == "org-a"

    wrong = auth.create_access_token({"sub": "operator", "cv": 1, "org": "org-b"})
    with pytest.raises(HTTPException):
        auth.authenticate_access_token(wrong)
