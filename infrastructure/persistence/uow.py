"""Unit of Work for atomic aggregate, authority, event and command persistence."""
from __future__ import annotations

from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from .authority_repositories import AuthorityRepository
from .command_repository import CommandRepository
from .repositories import ActorRepository, EventStore, OrganizationRepository, WorkflowRepository


class UnitOfWork(AbstractContextManager["UnitOfWork"]):
    """Groups repository writes into one database transaction."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.actors = ActorRepository(session)
        self.workflows = WorkflowRepository(session)
        self.events = EventStore(session)
        self.commands = CommandRepository(session)
        self.authority = AuthorityRepository(session)

    def __enter__(self) -> "UnitOfWork":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if exc_type is not None:
            self.session.rollback()
            return None
        self.session.commit()
        return None
