"""Persistence operations for Phase 2 command idempotency."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import CommandExecutionModel


@dataclass(frozen=True)
class CommandExecution:
    command_id: str
    organization_id: str
    actor_id: str
    command_type: str
    payload: dict[str, Any]
    aggregate_id: Optional[str]
    created_at: datetime


class CommandRepository:
    """Stores durable command receipts used for idempotent execution."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, command_id: str) -> Optional[CommandExecution]:
        row = self.session.get(CommandExecutionModel, command_id)
        if row is None:
            return None
        return CommandExecution(
            command_id=row.command_id,
            organization_id=row.organization_id,
            actor_id=row.actor_id,
            command_type=row.command_type,
            payload=row.payload,
            aggregate_id=row.aggregate_id,
            created_at=row.created_at,
        )

    def add(
        self,
        *,
        command_id: str,
        organization_id: str,
        actor_id: str,
        command_type: str,
        payload: dict[str, Any],
        aggregate_id: Optional[str],
        created_at: datetime,
    ) -> None:
        self.session.add(
            CommandExecutionModel(
                command_id=command_id,
                organization_id=organization_id,
                actor_id=actor_id,
                command_type=command_type,
                payload=payload,
                aggregate_id=aggregate_id,
                created_at=created_at,
            )
        )
