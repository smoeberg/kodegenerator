"""Tenant-scoped append-only evaluation and performance persistence."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from phase4.adaptation.performance import PerformanceObservation, PerformanceSnapshot
from phase4.council.configuration import IndependenceLevel
from phase4.verification.evaluation import (
    EvaluationRecord,
    EvaluationRubric,
    RubricCriterion,
)

from .database import apply_tenant_context
from .evaluation_models import (
    BotPerformanceObservationModel,
    BotPerformanceSnapshotModel,
    EvaluationRecordModel,
    EvaluationRubricModel,
)


class EvaluationStoreConflictError(RuntimeError):
    pass


class EvaluationStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def add_rubric(self, value: EvaluationRubric) -> EvaluationRubric:
        row = EvaluationRubricModel(
            organization_id=value.organization_id,
            rubric_id=value.rubric_id,
            version=value.version,
            subject_classes=list(value.subject_classes),
            criteria=[item.__dict__ for item in value.criteria],
            pass_threshold=value.pass_threshold,
            independence_level=value.independence_level.value,
            fingerprint=value.fingerprint,
            created_at=value.created_at,
        )
        self._insert(row, "rubric version already exists")
        return value

    def get_rubric(
        self, organization_id: str, rubric_id: str, version: int
    ) -> EvaluationRubric | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(
                EvaluationRubricModel, (organization_id, rubric_id, version)
            )
            if row is None:
                return None
            value = EvaluationRubric(
                organization_id=row.organization_id,
                rubric_id=row.rubric_id,
                version=row.version,
                subject_classes=tuple(row.subject_classes),
                criteria=tuple(RubricCriterion(**item) for item in row.criteria),
                pass_threshold=row.pass_threshold,
                independence_level=IndependenceLevel(row.independence_level),
                created_at=_utc(row.created_at),
            )
            if value.fingerprint != row.fingerprint:
                raise EvaluationStoreConflictError("rubric fingerprint is invalid")
            return value

    def append_evaluation(self, value: EvaluationRecord) -> EvaluationRecord:
        row = EvaluationRecordModel(
            organization_id=value.organization_id,
            evaluation_id=value.evaluation_id,
            subject_id=value.subject_id,
            subject_class=value.subject_class,
            subject_fingerprint=value.subject_fingerprint,
            rubric_id=value.rubric_id,
            rubric_version=value.rubric_version,
            rubric_fingerprint=value.rubric_fingerprint,
            base_sha=value.base_sha,
            producer=value.producer.__dict__,
            evaluator=None if value.evaluator is None else value.evaluator.__dict__,
            checks=[item.__dict__ for item in value.checks],
            semantic_evidence=list(value.semantic_evidence),
            hard_failures=list(value.hard_failures),
            outcome=value.outcome.value,
            score=value.score,
            confidence=value.confidence,
            provenance=[list(item) for item in value.provenance],
            fingerprint=value.content_fingerprint,
            created_at=value.created_at,
        )
        self._insert(row, "evaluation already exists")
        return value

    def append_observation(
        self, value: PerformanceObservation
    ) -> PerformanceObservation:
        if (
            value.supersedes_observation_id is not None
            and self.get_observation(
                value.organization_id, value.supersedes_observation_id
            )
            is None
        ):
            raise EvaluationStoreConflictError("superseded observation does not exist")
        row = BotPerformanceObservationModel(**value.__dict__)
        self._insert(row, "observation or ledger position already exists")
        return value

    def get_observation(
        self, organization_id: str, observation_id: str
    ) -> PerformanceObservation | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(
                BotPerformanceObservationModel, (organization_id, observation_id)
            )
            return (
                None
                if row is None
                else PerformanceObservation(
                    **{
                        key: _observation_value(row, key)
                        for key in PerformanceObservation.__dataclass_fields__
                    }
                )
            )

    def next_ledger_position(self, organization_id: str) -> int:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            value = session.scalar(
                select(func.max(BotPerformanceObservationModel.ledger_position)).where(
                    BotPerformanceObservationModel.organization_id == organization_id
                )
            )
            return int(value or 0) + 1

    def add_snapshot(self, value: PerformanceSnapshot) -> PerformanceSnapshot:
        latest = self.next_ledger_position(value.organization_id) - 1
        if value.ledger_position > latest:
            raise EvaluationStoreConflictError(
                "snapshot cannot include an uncommitted ledger position"
            )
        row = BotPerformanceSnapshotModel(
            organization_id=value.organization_id,
            snapshot_id=value.snapshot_id,
            bot_profile_id=value.bot_profile_id,
            role_id=value.role_id,
            task_context=value.task_context,
            sample_count=value.sample_count,
            window_start=value.window_start,
            window_end=value.window_end,
            definitions=[list(item) for item in value.definitions],
            values=[list(item) for item in value.values],
            confidence=value.confidence,
            decay_version=value.decay_version,
            exclusions=list(value.exclusions),
            ledger_position=value.ledger_position,
            fingerprint=value.fingerprint,
            created_at=value.created_at,
        )
        self._insert(row, "snapshot already exists")
        return value

    def observations_through(
        self, organization_id: str, ledger_position: int
    ) -> tuple[PerformanceObservation, ...]:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            rows = session.scalars(
                select(BotPerformanceObservationModel)
                .where(
                    BotPerformanceObservationModel.organization_id == organization_id,
                    BotPerformanceObservationModel.ledger_position <= ledger_position,
                )
                .order_by(BotPerformanceObservationModel.ledger_position)
            ).all()
            return tuple(
                PerformanceObservation(
                    **{
                        key: _observation_value(row, key)
                        for key in PerformanceObservation.__dataclass_fields__
                    }
                )
                for row in rows
            )

    def get_snapshot(
        self, organization_id: str, snapshot_id: str
    ) -> PerformanceSnapshot | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(
                BotPerformanceSnapshotModel, (organization_id, snapshot_id)
            )
            if row is None:
                return None
            value = PerformanceSnapshot(
                organization_id=row.organization_id,
                snapshot_id=row.snapshot_id,
                bot_profile_id=row.bot_profile_id,
                role_id=row.role_id,
                task_context=row.task_context,
                sample_count=row.sample_count,
                window_start=_utc(row.window_start),
                window_end=_utc(row.window_end),
                definitions=tuple(tuple(item) for item in row.definitions),
                values=tuple((item[0], float(item[1])) for item in row.values),
                confidence=row.confidence,
                decay_version=row.decay_version,
                exclusions=tuple(row.exclusions),
                ledger_position=row.ledger_position,
                created_at=_utc(row.created_at),
            )
            if value.fingerprint != row.fingerprint:
                raise EvaluationStoreConflictError("snapshot fingerprint is invalid")
            return value

    def _insert(self, row, message: str) -> None:
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, row.organization_id)
                session.add(row)
        except IntegrityError as exc:
            raise EvaluationStoreConflictError(message) from exc


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def _observation_value(row, key: str):
    if key == "event_time":
        return _utc(row.event_time)
    if key == "evidence":
        return tuple(row.evidence)
    return getattr(row, key)
