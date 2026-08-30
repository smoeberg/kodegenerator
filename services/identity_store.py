"""Durable authentication-principal persistence boundary."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from infrastructure.persistence.models import IdentityPrincipalModel


class IdentityStore:
    """Share authentication principals across API processes."""

    def __init__(self, session_factory: Any) -> None:
        self._sessions = session_factory

    def get(self, username: str) -> dict[str, Any] | None:
        normalized = _normalize_username(username)
        with self._sessions() as session:
            row = session.get(IdentityPrincipalModel, normalized)
            return _as_dict(row) if row is not None else None

    def create_if_absent(
        self,
        *,
        username: str,
        hashed_password: str,
        email: str | None = None,
        full_name: str | None = None,
    ) -> dict[str, Any]:
        normalized = _normalize_username(username)
        now = datetime.now(timezone.utc)
        row = IdentityPrincipalModel(
            username=normalized,
            email=email,
            full_name=full_name,
            hashed_password=hashed_password,
            disabled=False,
            credential_version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._sessions() as session, session.begin():
                existing = session.get(IdentityPrincipalModel, normalized)
                if existing is not None:
                    return _as_dict(existing)
                session.add(row)
        except IntegrityError:
            existing = self.get(normalized)
            if existing is None:
                raise
            return existing
        return _as_dict(row)

    def rotate_password(self, username: str, hashed_password: str) -> None:
        normalized = _normalize_username(username)
        with self._sessions() as session, session.begin():
            row = session.get(IdentityPrincipalModel, normalized)
            if row is None:
                raise KeyError(normalized)
            row.hashed_password = hashed_password
            row.credential_version += 1
            row.updated_at = datetime.now(timezone.utc)

    def set_disabled(self, username: str, disabled: bool) -> None:
        normalized = _normalize_username(username)
        with self._sessions() as session, session.begin():
            row = session.get(IdentityPrincipalModel, normalized)
            if row is None:
                raise KeyError(normalized)
            row.disabled = disabled
            row.credential_version += 1
            row.updated_at = datetime.now(timezone.utc)


def _normalize_username(username: str) -> str:
    if not isinstance(username, str) or not username.strip():
        raise ValueError("username is required")
    return username.strip().casefold()


def _as_dict(row: IdentityPrincipalModel) -> dict[str, Any]:
    return {
        "username": row.username,
        "email": row.email,
        "full_name": row.full_name,
        "hashed_password": row.hashed_password,
        "disabled": row.disabled,
        "credential_version": row.credential_version,
    }
