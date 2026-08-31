"""Tenant-scoped OCC persistence for integration plans and receipts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.factory_integration import (
    IntegrationCandidate,
    IntegrationPlan,
    IntegrationReceipt,
    IntegrationStatus,
)
from services.side_effects import canonical_fingerprint

from .database import apply_tenant_context
from .factory_integration_models import (
    FactoryIntegrationPlanModel,
    FactoryIntegrationReceiptModel,
)
from .models import TerminalSideEffectModel


class IntegrationStoreConflictError(RuntimeError):
    pass


class FactoryIntegrationStore:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._sessions = session_factory

    def create_plan(self, value: IntegrationPlan) -> IntegrationPlan:
        row = FactoryIntegrationPlanModel(
            organization_id=value.organization_id,
            plan_id=value.plan_id,
            workflow_id=value.workflow_id,
            payload=_plan_payload(value),
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
            replay = self.get_plan(value.organization_id, value.plan_id)
            if replay and replay.content_fingerprint == value.content_fingerprint:
                return replay
            raise IntegrationStoreConflictError("integration plan conflicts") from exc
        return value

    def get_plan(self, organization_id: str, plan_id: str) -> IntegrationPlan | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.get(FactoryIntegrationPlanModel, (organization_id, plan_id))
            if row is None:
                return None
            value = _plan(row)
            if value.content_fingerprint != row.fingerprint:
                raise IntegrationStoreConflictError("plan fingerprint is invalid")
            return value

    def save_plan(
        self, value: IntegrationPlan, *, expected_version: int
    ) -> IntegrationPlan:
        with self._sessions() as session, session.begin():
            apply_tenant_context(session, value.organization_id)
            result = session.execute(
                update(FactoryIntegrationPlanModel)
                .where(
                    FactoryIntegrationPlanModel.organization_id
                    == value.organization_id,
                    FactoryIntegrationPlanModel.plan_id == value.plan_id,
                    FactoryIntegrationPlanModel.version == expected_version,
                    FactoryIntegrationPlanModel.fingerprint
                    == value.content_fingerprint,
                )
                .values(status=value.status.value, version=value.version)
            )
            if result.rowcount != 1:
                raise IntegrationStoreConflictError("stale integration-plan writer")
        return value

    def get_receipt_for_plan(
        self, organization_id: str, plan_fingerprint: str
    ) -> IntegrationReceipt | None:
        with self._sessions() as session:
            apply_tenant_context(session, organization_id)
            row = session.scalar(
                select(FactoryIntegrationReceiptModel).where(
                    FactoryIntegrationReceiptModel.organization_id == organization_id,
                    FactoryIntegrationReceiptModel.plan_fingerprint == plan_fingerprint,
                )
            )
            if row is None:
                return None
            data = row.payload
            value = IntegrationReceipt(
                organization_id=organization_id,
                receipt_id=row.receipt_id,
                plan_id=row.plan_id,
                plan_fingerprint=row.plan_fingerprint,
                side_effect_idempotency_key=data["side_effect_idempotency_key"],
                side_effect_request_fingerprint=data["side_effect_request_fingerprint"],
                integration_branch=data["integration_branch"],
                integration_head_sha=data["integration_head_sha"],
                integrated_candidate_ids=tuple(data["integrated_candidate_ids"]),
                conflict_paths=tuple(data["conflict_paths"]),
                suite_attestation=tuple(
                    tuple(item) for item in data["suite_attestation"]
                ),
                status=IntegrationStatus(row.status),
                completed_at=_utc(row.completed_at),
            )
            if value.content_fingerprint != row.fingerprint:
                raise IntegrationStoreConflictError("receipt fingerprint is invalid")
            return value

    def append_receipt(
        self, value: IntegrationReceipt, *, side_effect_result: dict
    ) -> IntegrationReceipt:
        if value.content_fingerprint != value.receipt_id:
            raise IntegrationStoreConflictError("receipt ID must equal its fingerprint")
        try:
            with self._sessions() as session, session.begin():
                apply_tenant_context(session, value.organization_id)
                plan = session.get(
                    FactoryIntegrationPlanModel,
                    (value.organization_id, value.plan_id),
                )
                effect = session.scalar(
                    select(TerminalSideEffectModel).where(
                        TerminalSideEffectModel.organization_id
                        == value.organization_id,
                        TerminalSideEffectModel.action == "factory.integrate",
                        TerminalSideEffectModel.idempotency_key
                        == value.side_effect_idempotency_key,
                    )
                )
                if plan is None or plan.fingerprint != value.plan_fingerprint:
                    raise IntegrationStoreConflictError(
                        "receipt plan binding is invalid"
                    )
                if (
                    effect is None
                    or effect.status != "completed"
                    or effect.request_fingerprint
                    != value.side_effect_request_fingerprint
                    or dict(effect.result or {}) != side_effect_result
                    or canonical_fingerprint(side_effect_result)
                    != dict(value.suite_attestation).get("result_fingerprint")
                ):
                    raise IntegrationStoreConflictError(
                        "receipt does not match completed integration effect"
                    )
                session.add(
                    FactoryIntegrationReceiptModel(
                        organization_id=value.organization_id,
                        receipt_id=value.receipt_id,
                        plan_id=value.plan_id,
                        plan_fingerprint=value.plan_fingerprint,
                        status=value.status.value,
                        payload={
                            key: item
                            for key, item in value.__dict__.items()
                            if key != "completed_at"
                        },
                        fingerprint=value.content_fingerprint,
                        completed_at=value.completed_at,
                    )
                )
        except IntegrityError as exc:
            replay = self.get_receipt_for_plan(
                value.organization_id, value.plan_fingerprint
            )
            if replay and replay.content_fingerprint == value.content_fingerprint:
                return replay
            raise IntegrationStoreConflictError(
                "integration receipt already exists"
            ) from exc
        return value


def _plan_payload(value: IntegrationPlan) -> dict:
    return {
        "repository": value.repository,
        "base_sha": value.base_sha,
        "candidates": [candidate.__dict__ for candidate in value.candidates],
        "dependency_evidence": list(value.dependency_evidence),
        "compatibility_evidence": list(value.compatibility_evidence),
        "integration_branch": value.integration_branch,
        "required_checks": list(value.required_checks),
        "authority_action": value.authority_action,
    }


def _plan(row: FactoryIntegrationPlanModel) -> IntegrationPlan:
    data = row.payload
    return IntegrationPlan(
        organization_id=row.organization_id,
        plan_id=row.plan_id,
        workflow_id=row.workflow_id,
        repository=data["repository"],
        base_sha=data["base_sha"],
        candidates=tuple(
            IntegrationCandidate(
                candidate_id=item["candidate_id"],
                selection_id=item["selection_id"],
                work_package_fingerprint=item["work_package_fingerprint"],
                head_sha=item["head_sha"],
                commit_shas=tuple(item["commit_shas"]),
            )
            for item in data["candidates"]
        ),
        dependency_evidence=tuple(data["dependency_evidence"]),
        compatibility_evidence=tuple(data["compatibility_evidence"]),
        integration_branch=data["integration_branch"],
        required_checks=tuple(data["required_checks"]),
        idempotency_key=row.idempotency_key,
        authority_action=data["authority_action"],
        status=IntegrationStatus(row.status),
        version=row.version,
        created_at=_utc(row.created_at),
    )


def _utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )
