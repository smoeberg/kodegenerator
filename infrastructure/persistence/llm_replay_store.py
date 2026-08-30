"""Durable fenced replay ledger for governed model calls."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.llm_replay import (
    LLMCallInProgressError,
    LLMReplayClaim,
    LLMReplayConflictError,
)

from .database import apply_tenant_context
from .models import GovernedLLMCallModel


class SQLAlchemyLLMReplayStore:
    """Coordinate model calls across workers with leases and fencing tokens."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        lease_seconds: int = 180,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("lease_seconds must be a positive integer")
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def claim(
        self, organization_id: str, idempotency_key: str, prompt_fingerprint: str
    ) -> LLMReplayClaim:
        now = self._clock()
        token = secrets.token_hex(16)
        row = GovernedLLMCallModel(
            organization_id=organization_id,
            idempotency_key=idempotency_key,
            prompt_fingerprint=prompt_fingerprint,
            status="in_progress",
            fencing_token=token,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
            created_at=now,
            updated_at=now,
        )
        try:
            with self._session_factory() as session, session.begin():
                apply_tenant_context(session, organization_id)
                session.add(row)
            return LLMReplayClaim(token)
        except IntegrityError:
            pass
        with self._session_factory() as session, session.begin():
            apply_tenant_context(session, organization_id)
            current = session.scalar(
                select(GovernedLLMCallModel).where(
                    GovernedLLMCallModel.organization_id == organization_id,
                    GovernedLLMCallModel.idempotency_key == idempotency_key,
                )
            )
            assert current is not None
            if current.prompt_fingerprint != prompt_fingerprint:
                raise LLMReplayConflictError(
                    "idempotency key is bound to different input"
                )
            if current.status == "completed":
                return LLMReplayClaim(
                    None, dict(current.value or {}), dict(current.provenance or {})
                )
            lease_expires_at = current.lease_expires_at
            if lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=timezone.utc)
            if current.status == "in_progress" and lease_expires_at > now:
                raise LLMCallInProgressError("LLM call is already in progress")
            old_token = current.fencing_token
            statement = (
                update(GovernedLLMCallModel)
                .where(
                    GovernedLLMCallModel.organization_id == organization_id,
                    GovernedLLMCallModel.idempotency_key == idempotency_key,
                    GovernedLLMCallModel.fencing_token == old_token,
                )
                .values(
                    status="in_progress",
                    fencing_token=token,
                    lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                    failure_class=None,
                    updated_at=now,
                )
            )
            if session.execute(statement).rowcount != 1:
                raise LLMCallInProgressError("LLM lease changed during recovery")
            return LLMReplayClaim(token)

    def complete(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        value: dict,
        provenance: dict,
    ) -> None:
        self._finish(
            organization_id,
            idempotency_key,
            prompt_fingerprint,
            fencing_token,
            status="completed",
            value=value,
            provenance=provenance,
            failure_class=None,
        )

    def fail(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        failure_class: str,
    ) -> None:
        self._finish(
            organization_id,
            idempotency_key,
            prompt_fingerprint,
            fencing_token,
            status="failed",
            value=None,
            provenance=None,
            failure_class=failure_class,
        )

    def _finish(
        self,
        organization_id: str,
        idempotency_key: str,
        prompt_fingerprint: str,
        fencing_token: str,
        *,
        status: str,
        value: dict | None,
        provenance: dict | None,
        failure_class: str | None,
    ) -> None:
        now = self._clock()
        with self._session_factory() as session, session.begin():
            apply_tenant_context(session, organization_id)
            statement = (
                update(GovernedLLMCallModel)
                .where(
                    GovernedLLMCallModel.organization_id == organization_id,
                    GovernedLLMCallModel.idempotency_key == idempotency_key,
                    GovernedLLMCallModel.prompt_fingerprint == prompt_fingerprint,
                    GovernedLLMCallModel.fencing_token == fencing_token,
                    GovernedLLMCallModel.status == "in_progress",
                )
                .values(
                    status=status,
                    value=value,
                    provenance=provenance,
                    failure_class=failure_class,
                    lease_expires_at=now,
                    updated_at=now,
                )
            )
            if session.execute(statement).rowcount != 1:
                raise LLMCallInProgressError("stale LLM fencing token")
