"""Database engine/session management for DOR Foundation v0.1."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Owns the SQLAlchemy engine and session factory."""

    def __init__(self, url: str | None = None) -> None:
        if url is None:
            url = os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db")
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _enable_sqlite_foreign_keys(dbapi_connection, connection_record) -> None:
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
        self.session_factory = sessionmaker(
            bind=self.engine,
            expire_on_commit=False,
            class_=Session,
        )

    @contextmanager
    def session(self, organization_id: str | None = None) -> Iterator[Session]:
        """Yield a session bound to one tenant for PostgreSQL RLS.

        Tenant-owned canonical runtime tables are protected by PostgreSQL row
        security. ``set_config(..., true)`` scopes the organization value to
        the current transaction, so pooled connections cannot leak tenant
        context into a later request. SQLite keeps the same explicit repository
        filtering used by tests and local development.
        """
        session = self.session_factory()
        try:
            if organization_id is not None:
                apply_tenant_context(session, organization_id)
            else:
                session.info["organization_id"] = None
            yield session
        finally:
            session.close()


def apply_tenant_context(session: Session, organization_id: str) -> str:
    """Bind an existing SQLAlchemy transaction to exactly one organization."""
    normalized = organization_id.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("organization_id must contain 1-128 characters")
    existing = session.info.get("organization_id")
    if existing not in (None, normalized):
        raise RuntimeError("session is already bound to another organization")
    session.info["organization_id"] = normalized
    if session.get_bind().dialect.name == "postgresql":
        session.execute(
            text(
                "SELECT set_config('dor.organization_id', "
                ":organization_id, true)"
            ),
            {"organization_id": normalized},
        )
    return normalized
