"""Tenant-scoped OCC store for packages and immutable candidate deliveries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.factory_work import (
    CandidateDelivery,
    CandidateSelection,
    ExecutionMode,
    WorkPackage,
    WorkPackageStatus,
    WriteScope,
)

from .database import apply_tenant_context
from .factory_models import (
    FactoryCandidateDeliveryModel,
    FactoryCandidateSelectionModel,
    FactoryWorkPackageModel,
)


class FactoryStoreConflictError(RuntimeError):
    pass


class FactoryStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def create_package(self, value: WorkPackage) -> WorkPackage:
        row = FactoryWorkPackageModel(
            organization_id=value.organization_id,
            work_package_id=value.work_package_id,
            logical_task_id=value.logical_task_id,
            workflow_id=value.workflow_id,
            payload=_package_payload(value),
            fingerprint=value.content_fingerprint,
            idempotency_key=value.idempotency_key,
            status=value.status.value,
            version=value.version,
            created_at=value.created_at,
        )
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, value.organization_id)
                session.add(row)
        except IntegrityError as exc:
            replay = self.get_package(value.organization_id, value.work_package_id)
            if (
                replay is not None
                and replay.content_fingerprint == value.content_fingerprint
            ):
                return replay
            raise FactoryStoreConflictError(
                "package conflicts with durable state"
            ) from exc
        return value

    def get_package(
        self, organization_id: str, work_package_id: str
    ) -> WorkPackage | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(
                FactoryWorkPackageModel, (organization_id, work_package_id)
            )
            if row is None:
                return None
            value = _package(row)
            if value.content_fingerprint != row.fingerprint:
                raise FactoryStoreConflictError("package fingerprint is invalid")
            return value

    def save_package(self, value: WorkPackage, *, expected_version: int) -> WorkPackage:
        with self._sessions() as session, session.begin():
            apply_tenant_context(session, value.organization_id)
            result = session.execute(
                update(FactoryWorkPackageModel)
                .where(
                    FactoryWorkPackageModel.organization_id == value.organization_id,
                    FactoryWorkPackageModel.work_package_id == value.work_package_id,
                    FactoryWorkPackageModel.version == expected_version,
                    FactoryWorkPackageModel.fingerprint == value.content_fingerprint,
                )
                .values(status=value.status.value, version=value.version)
            )
            if result.rowcount != 1:
                raise FactoryStoreConflictError(
                    "stale package writer or changed package content"
                )
        return value

    def append_candidate(self, value: CandidateDelivery) -> CandidateDelivery:
        row = FactoryCandidateDeliveryModel(
            organization_id=value.organization_id,
            candidate_id=value.candidate_id,
            work_package_id=value.work_package_id,
            execution_id=value.execution_id,
            head_sha=value.head_sha,
            payload={
                key: item
                for key, item in value.__dict__.items()
                if key != "delivered_at"
            },
            fingerprint=value.content_fingerprint,
            delivered_at=value.delivered_at,
        )
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, value.organization_id)
                package = session.get(
                    FactoryWorkPackageModel,
                    (value.organization_id, value.work_package_id),
                )
                if (
                    package is None
                    or package.fingerprint != value.work_package_fingerprint
                ):
                    raise FactoryStoreConflictError(
                        "candidate package binding is invalid"
                    )
                session.add(row)
        except IntegrityError as exc:
            raise FactoryStoreConflictError(
                "candidate delivery already exists"
            ) from exc
        return value

    def get_candidate(
        self, organization_id: str, candidate_id: str
    ) -> CandidateDelivery | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(
                FactoryCandidateDeliveryModel, (organization_id, candidate_id)
            )
            if row is None:
                return None
            data = row.payload
            value = CandidateDelivery(
                organization_id=organization_id,
                candidate_id=candidate_id,
                work_package_id=row.work_package_id,
                work_package_fingerprint=data["work_package_fingerprint"],
                execution_id=row.execution_id,
                assignment_id=data["assignment_id"],
                base_sha=data["base_sha"],
                branch=data["branch"],
                head_sha=row.head_sha,
                commit_shas=tuple(data["commit_shas"]),
                patch_fingerprint=data["patch_fingerprint"],
                affected_paths=tuple(data["affected_paths"]),
                attestations=tuple(data["attestations"]),
                delivered_at=_utc(row.delivered_at),
            )
            if value.content_fingerprint != row.fingerprint:
                raise FactoryStoreConflictError("candidate fingerprint is invalid")
            return value

    def append_selection(self, value: CandidateSelection) -> CandidateSelection:
        row = FactoryCandidateSelectionModel(
            organization_id=value.organization_id,
            selection_id=value.selection_id,
            logical_task_id=value.logical_task_id,
            work_package_fingerprint=value.work_package_fingerprint,
            winner_candidate_id=value.winner_candidate_id,
            payload={
                key: item for key, item in value.__dict__.items() if key != "created_at"
            },
            fingerprint=value.content_fingerprint,
            created_at=value.created_at,
        )
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, value.organization_id)
                candidates = (
                    session.query(FactoryCandidateDeliveryModel)
                    .filter(
                        FactoryCandidateDeliveryModel.organization_id
                        == value.organization_id,
                        FactoryCandidateDeliveryModel.candidate_id.in_(
                            value.candidate_ids
                        ),
                    )
                    .all()
                )
                if len(candidates) != len(value.candidate_ids) or any(
                    candidate.payload["work_package_fingerprint"]
                    != value.work_package_fingerprint
                    for candidate in candidates
                ):
                    raise FactoryStoreConflictError(
                        "selection candidate binding is invalid"
                    )
                session.add(row)
        except IntegrityError as exc:
            raise FactoryStoreConflictError(
                "selection conflicts with an existing winner"
            ) from exc
        return value

    def get_selection(
        self, organization_id: str, selection_id: str
    ) -> CandidateSelection | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(
                FactoryCandidateSelectionModel, (organization_id, selection_id)
            )
            if row is None:
                return None
            data = row.payload
            value = CandidateSelection(
                organization_id=organization_id,
                selection_id=selection_id,
                logical_task_id=row.logical_task_id,
                work_package_fingerprint=row.work_package_fingerprint,
                candidate_ids=tuple(data["candidate_ids"]),
                rubric_fingerprint=data["rubric_fingerprint"],
                evaluation_ids=tuple(data["evaluation_ids"]),
                excluded_candidate_ids=tuple(data["excluded_candidate_ids"]),
                winner_candidate_id=row.winner_candidate_id,
                evaluator_assignment_id=data["evaluator_assignment_id"],
                authority_decision_id=data["authority_decision_id"],
                created_at=_utc(row.created_at),
            )
            if value.content_fingerprint != row.fingerprint:
                raise FactoryStoreConflictError("selection fingerprint is invalid")
            return value


def _package_payload(value: WorkPackage) -> dict:
    return {
        "requirements_fingerprint": value.requirements_fingerprint,
        "architecture_fingerprint": value.architecture_fingerprint,
        "contract_fingerprint": value.contract_fingerprint,
        "base_sha": value.base_sha,
        "dependency_ids": list(value.dependency_ids),
        "criterion_ids": list(value.criterion_ids),
        "required_checks": list(value.required_checks),
        "write_scope": {
            "allowed_paths": list(value.write_scope.allowed_paths),
            "denied_paths": list(value.write_scope.denied_paths),
        },
        "execution_mode": value.execution_mode.value,
        "candidate_count": value.candidate_count,
        "allocation_id": value.allocation_id,
        "allocation_version": value.allocation_version,
        "policy_fingerprint": value.policy_fingerprint,
        "token_budget": value.token_budget,
        "time_budget_seconds": value.time_budget_seconds,
    }


def _package(row: FactoryWorkPackageModel) -> WorkPackage:
    data = row.payload
    return WorkPackage(
        organization_id=row.organization_id,
        work_package_id=row.work_package_id,
        logical_task_id=row.logical_task_id,
        workflow_id=row.workflow_id,
        requirements_fingerprint=data["requirements_fingerprint"],
        architecture_fingerprint=data["architecture_fingerprint"],
        contract_fingerprint=data["contract_fingerprint"],
        base_sha=data["base_sha"],
        dependency_ids=tuple(data["dependency_ids"]),
        criterion_ids=tuple(data["criterion_ids"]),
        required_checks=tuple(data["required_checks"]),
        write_scope=WriteScope(
            tuple(data["write_scope"]["allowed_paths"]),
            tuple(data["write_scope"]["denied_paths"]),
        ),
        execution_mode=ExecutionMode(data["execution_mode"]),
        candidate_count=data["candidate_count"],
        allocation_id=data["allocation_id"],
        allocation_version=data["allocation_version"],
        policy_fingerprint=data["policy_fingerprint"],
        token_budget=data["token_budget"],
        time_budget_seconds=data["time_budget_seconds"],
        idempotency_key=row.idempotency_key,
        status=WorkPackageStatus(row.status),
        version=row.version,
        created_at=_utc(row.created_at),
    )


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
