"""Database engine/session management for DOR Foundation v0.1."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


class Database:
    """Owns the SQLAlchemy engine and session factory.

    Schema creation/migration is intentionally not hidden in repository methods;
    boot is responsible for establishing a ready database before requests run.
    """

    def __init__(self, url: str = "sqlite:///./dor_runtime.db") -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, future=True, connect_args=connect_args)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()
