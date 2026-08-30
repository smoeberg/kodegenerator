"""JWT signing-key rotation and revocation security tests."""

from __future__ import annotations

import json

import pytest
from fastapi import HTTPException
from jose import jwt

import api.auth as auth
from services.jwt_keyring import JWTKeyConfigurationError, JWTKeyRing


KEY_A = "a" * 40
KEY_B = "b" * 40


@pytest.fixture(autouse=True)
def configured_user(monkeypatch):
    monkeypatch.delenv("DOR_IDENTITY_DATABASE_URL", raising=False)
    monkeypatch.setattr(auth, "_identity_store", None)
    monkeypatch.setattr(auth, "_identity_store_url", None)
    monkeypatch.setitem(
        auth.fake_users_db,
        "operator",
        {
            "username": "operator",
            "hashed_password": auth.get_password_hash("password"),
            "disabled": False,
            "credential_version": 1,
        },
    )
    yield
    auth.fake_users_db.pop("operator", None)


def _configure(monkeypatch, *, active: str, revoked: str = "") -> None:
    monkeypatch.setenv("DOR_JWT_SIGNING_KEYS", json.dumps({"key-a": KEY_A, "key-b": KEY_B}))
    monkeypatch.setenv("DOR_JWT_ACTIVE_KEY_ID", active)
    monkeypatch.setenv("DOR_JWT_REVOKED_KEY_IDS", revoked)


def test_rotation_keeps_previous_key_valid_during_overlap(monkeypatch) -> None:
    _configure(monkeypatch, active="key-a")
    old_token = auth.create_access_token({"sub": "operator", "cv": 1})
    assert jwt.get_unverified_header(old_token)["kid"] == "key-a"

    _configure(monkeypatch, active="key-b")
    new_token = auth.create_access_token({"sub": "operator", "cv": 1})

    assert auth.authenticate_access_token(old_token).username == "operator"
    assert auth.authenticate_access_token(new_token).username == "operator"
    assert jwt.get_unverified_header(new_token)["kid"] == "key-b"


def test_revoked_signing_key_invalidates_existing_tokens(monkeypatch) -> None:
    _configure(monkeypatch, active="key-a")
    token = auth.create_access_token({"sub": "operator", "cv": 1})
    _configure(monkeypatch, active="key-b", revoked="key-a")

    with pytest.raises(HTTPException) as exc_info:
        auth.authenticate_access_token(token)
    assert exc_info.value.status_code == 401


def test_unknown_key_id_never_falls_back_to_active_key(monkeypatch) -> None:
    _configure(monkeypatch, active="key-a")
    forged = jwt.encode(
        {"sub": "operator", "cv": 1},
        KEY_A,
        algorithm=auth.ALGORITHM,
        headers={"kid": "unknown"},
    )

    with pytest.raises(HTTPException):
        auth.authenticate_access_token(forged)


def test_token_without_key_id_is_rejected(monkeypatch) -> None:
    _configure(monkeypatch, active="key-a")
    legacy_header_token = jwt.encode(
        {"sub": "operator", "cv": 1}, KEY_A, algorithm=auth.ALGORITHM
    )

    with pytest.raises(HTTPException):
        auth.authenticate_access_token(legacy_header_token)


def test_active_key_cannot_be_revoked(monkeypatch) -> None:
    _configure(monkeypatch, active="key-a", revoked="key-a")

    with pytest.raises(JWTKeyConfigurationError, match="active JWT signing key"):
        JWTKeyRing.from_environment(production=True)


def test_production_rejects_short_hmac_key(monkeypatch) -> None:
    monkeypatch.setenv("DOR_JWT_SIGNING_KEYS", json.dumps({"short": "unsafe"}))
    monkeypatch.setenv("DOR_JWT_ACTIVE_KEY_ID", "short")
    monkeypatch.delenv("DOR_JWT_REVOKED_KEY_IDS", raising=False)

    with pytest.raises(JWTKeyConfigurationError, match="at least 32"):
        JWTKeyRing.from_environment(production=True)
