"""Atomic tenant-scoped storage for immutable Council selections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.verification.allocation_selector import SelectionReceipt
from phase4.verification.assignment import (
    CouncilRunSelection,
    FrozenCouncilAssignment,
)

from .database import apply_tenant_context
from .selection_models import (
    CouncilFrozenAssignmentModel,
    CouncilSelectionRunModel,
)


class CouncilSelectionConflictError(RuntimeError):
    pass


class CouncilSelectionStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def freeze(self, value: CouncilRunSelection) -> CouncilRunSelection:
        existing = self.get(value.organization_id, value.run_id)
        if existing is not None:
            if existing.fingerprint != value.fingerprint:
                raise CouncilSelectionConflictError(
                    "run ID is already bound to a different selection"
                )
            return existing
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, value.organization_id)
                session.add(
                    CouncilSelectionRunModel(
                        organization_id=value.organization_id,
                        decision_id=value.fingerprint,
                        run_id=value.run_id,
                        template_id=value.template_id,
                        template_version=value.template_version,
                        template_fingerprint=value.template_fingerprint,
                        context_fingerprint=value.context_fingerprint,
                        scope_id=value.scope_id,
                        repository=value.repository,
                        base_sha=value.base_sha,
                        input_fingerprint=value.input_fingerprint,
                        selector_version=value.selector_version,
                        status=value.status,
                        rationale=value.rationale,
                        receipts=[receipt.__dict__ for receipt in value.receipts],
                        created_at=value.created_at,
                    )
                )
                session.flush()
                for index, assignment in enumerate(value.assignments):
                    session.add(
                        CouncilFrozenAssignmentModel(
                            organization_id=value.organization_id,
                            decision_id=value.fingerprint,
                            assignment_index=index,
                            **assignment.__dict__,
                        )
                    )
        except IntegrityError as exc:
            replay = self.get(value.organization_id, value.run_id)
            if replay is not None and replay.fingerprint == value.fingerprint:
                return replay
            raise CouncilSelectionConflictError(
                "Council selection conflicts with durable state"
            ) from exc
        return value

    def get(self, organization_id: str, run_id: str) -> CouncilRunSelection | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.scalar(
                select(CouncilSelectionRunModel).where(
                    CouncilSelectionRunModel.organization_id == organization_id,
                    CouncilSelectionRunModel.run_id == run_id,
                )
            )
            if row is None:
                return None
            assignments = session.scalars(
                select(CouncilFrozenAssignmentModel)
                .where(
                    CouncilFrozenAssignmentModel.organization_id == organization_id,
                    CouncilFrozenAssignmentModel.decision_id == row.decision_id,
                )
                .order_by(CouncilFrozenAssignmentModel.assignment_index)
            ).all()
            value = CouncilRunSelection(
                run_id=row.run_id,
                organization_id=row.organization_id,
                template_id=row.template_id,
                template_version=row.template_version,
                template_fingerprint=row.template_fingerprint,
                context_fingerprint=row.context_fingerprint,
                scope_id=row.scope_id,
                repository=row.repository,
                base_sha=row.base_sha,
                input_fingerprint=row.input_fingerprint,
                selector_version=row.selector_version,
                status=row.status,
                rationale=row.rationale,
                created_at=_utc(row.created_at),
                assignments=tuple(
                    FrozenCouncilAssignment(
                        **{
                            key: getattr(item, key)
                            for key in FrozenCouncilAssignment.__dataclass_fields__
                        }
                    )
                    for item in assignments
                ),
                receipts=tuple(
                    SelectionReceipt(
                        **{
                            key: item[key]
                            for key in SelectionReceipt.__dataclass_fields__
                        }
                    )
                    for item in row.receipts
                ),
            )
            if value.fingerprint != row.decision_id:
                raise CouncilSelectionConflictError(
                    "durable Council selection fingerprint is invalid"
                )
            return value


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
