"""SQLAlchemy implementation of terminal side-effect receipts."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from services.side_effects import (
    SideEffectClaim,
    SideEffectConflictError,
    SideEffectInProgressError,
)

from .database import apply_tenant_context
from .models import TerminalSideEffectModel


class SQLAlchemySideEffectStore:
    """Coordinate terminal mutations across workers with lease fencing."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        lease_seconds: int = 1800,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if type(lease_seconds) is not int or lease_seconds < 1:
            raise ValueError("lease_seconds must be a positive integer")
        self._sessions = session_factory
        self._lease_seconds = lease_seconds
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def claim(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
    ) -> SideEffectClaim:
        now, token = self._clock(), secrets.token_hex(16)
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, organization_id)
                session.add(
                    TerminalSideEffectModel(
                        organization_id=organization_id,
                        action=action,
                        idempotency_key=idempotency_key,
                        request_fingerprint=request_fingerprint,
                        status="in_progress",
                        fencing_token=token,
                        lease_expires_at=now + timedelta(seconds=self._lease_seconds),
                        created_at=now,
                        updated_at=now,
                    )
                )
            return SideEffectClaim(token)
        except IntegrityError:
            pass
        with self._sessions() as session, session.begin():
            apply_tenant_context(session, organization_id)
            row = session.scalar(
                select(TerminalSideEffectModel).where(
                    TerminalSideEffectModel.organization_id == organization_id,
                    TerminalSideEffectModel.action == action,
                    TerminalSideEffectModel.idempotency_key == idempotency_key,
                )
            )
            assert row is not None
            if row.request_fingerprint != request_fingerprint:
                raise SideEffectConflictError(
                    "side-effect key is bound to different input"
                )
            if row.status == "completed":
                return SideEffectClaim(None, dict(row.result or {}))
            expiry = row.lease_expires_at
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if row.status == "in_progress" and expiry > now:
                raise SideEffectInProgressError("side effect is already in progress")
            old_token = row.fencing_token
            statement = (
                update(TerminalSideEffectModel)
                .where(
                    TerminalSideEffectModel.organization_id == organization_id,
                    TerminalSideEffectModel.action == action,
                    TerminalSideEffectModel.idempotency_key == idempotency_key,
                    TerminalSideEffectModel.fencing_token == old_token,
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
                raise SideEffectInProgressError(
                    "side-effect lease changed during recovery"
                )
            return SideEffectClaim(token)

    def complete(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        result: dict,
    ) -> None:
        self._finish(
            organization_id,
            action,
            idempotency_key,
            request_fingerprint,
            fencing_token,
            "completed",
            result,
            None,
        )

    def fail(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        failure_class: str,
    ) -> None:
        self._finish(
            organization_id,
            action,
            idempotency_key,
            request_fingerprint,
            fencing_token,
            "failed",
            None,
            failure_class,
        )

    def _finish(
        self,
        organization_id: str,
        action: str,
        idempotency_key: str,
        request_fingerprint: str,
        fencing_token: str,
        status: str,
        result: dict | None,
        failure_class: str | None,
    ) -> None:
        now = self._clock()
        with self._sessions() as session, session.begin():
            apply_tenant_context(session, organization_id)
            statement = (
                update(TerminalSideEffectModel)
                .where(
                    TerminalSideEffectModel.organization_id == organization_id,
                    TerminalSideEffectModel.action == action,
                    TerminalSideEffectModel.idempotency_key == idempotency_key,
                    TerminalSideEffectModel.request_fingerprint == request_fingerprint,
                    TerminalSideEffectModel.fencing_token == fencing_token,
                    TerminalSideEffectModel.status == "in_progress",
                )
                .values(
                    status=status,
                    result=result,
                    failure_class=failure_class,
                    lease_expires_at=now,
                    updated_at=now,
                )
            )
            if session.execute(statement).rowcount != 1:
                raise SideEffectInProgressError("stale side-effect fencing token")
