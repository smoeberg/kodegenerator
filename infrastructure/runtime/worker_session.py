"""Per-job database session lifecycle for Phase 7 workers."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

from sqlalchemy.orm import Session


@contextmanager
def job_session(session_factory: Callable[[], Session]) -> Iterator[Session]:
    """Create, use, rollback-on-error, and always close one session per job."""
    session = session_factory()
    try:
        yield session
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
