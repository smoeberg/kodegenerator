"""Tenant-scoped, read-only access to immutable bot and factory evidence."""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from api.auth import User, get_current_active_user
from api.dependencies import (
    get_dor,
    get_evaluation_store,
    get_factory_integration_store,
    get_factory_store,
)
from api.schemas.bot_evidence import EvidenceResponse
from domain.principal import Principal
from infrastructure.persistence.evaluation_store import EvaluationStore
from infrastructure.persistence.factory_integration_store import FactoryIntegrationStore
from infrastructure.persistence.factory_store import FactoryStore
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError

router = APIRouter(prefix="/api/v1/bot-evidence", tags=["bot-evidence"])


def _membership(runtime: DORRuntime, user: User, organization_id: str) -> None:
    try:
        runtime.establish_context(
            principal=Principal(
                id=user.username, type="user", metadata={"username": user.username}
            ),
            organization_id=organization_id,
            actor_id=user.username,
        )
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=403, detail={"error": "organization_context_denied"}
        ) from exc


def _envelope(
    kind: str, identity: str, fingerprint: str, value: Any
) -> EvidenceResponse:
    return EvidenceResponse(
        organization_id=value.organization_id,
        evidence_type=kind,
        evidence_id=identity,
        fingerprint=fingerprint,
        payload=jsonable_encoder(asdict(value)),
    )


def _found(value):
    if value is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return value


@router.get("/evaluations/{evaluation_id}", response_model=EvidenceResponse)
def get_evaluation(
    evaluation_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: EvaluationStore = Depends(get_evaluation_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_evaluation(organization_id, evaluation_id))
    return _envelope("evaluation", evaluation_id, value.content_fingerprint, value)


@router.get("/rubrics/{rubric_id}/{version}", response_model=EvidenceResponse)
def get_rubric(
    rubric_id: str,
    version: int,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: EvaluationStore = Depends(get_evaluation_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_rubric(organization_id, rubric_id, version))
    return _envelope("rubric", f"{rubric_id}:{version}", value.fingerprint, value)


@router.get("/observations/{observation_id}", response_model=EvidenceResponse)
def get_observation(
    observation_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: EvaluationStore = Depends(get_evaluation_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_observation(organization_id, observation_id))
    return _envelope(
        "performance_observation", observation_id, value.fingerprint, value
    )


@router.get("/snapshots/{snapshot_id}", response_model=EvidenceResponse)
def get_snapshot(
    snapshot_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: EvaluationStore = Depends(get_evaluation_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_snapshot(organization_id, snapshot_id))
    return _envelope("performance_snapshot", snapshot_id, value.fingerprint, value)


@router.get("/work-packages/{package_id}", response_model=EvidenceResponse)
def get_work_package(
    package_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: FactoryStore = Depends(get_factory_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_package(organization_id, package_id))
    return _envelope("work_package", package_id, value.content_fingerprint, value)


@router.get("/candidates/{candidate_id}", response_model=EvidenceResponse)
def get_candidate(
    candidate_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: FactoryStore = Depends(get_factory_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_candidate(organization_id, candidate_id))
    return _envelope("candidate", candidate_id, value.content_fingerprint, value)


@router.get("/candidate-selections/{selection_id}", response_model=EvidenceResponse)
def get_candidate_selection(
    selection_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: FactoryStore = Depends(get_factory_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_selection(organization_id, selection_id))
    return _envelope(
        "candidate_selection", selection_id, value.content_fingerprint, value
    )


@router.get("/integration-plans/{plan_id}", response_model=EvidenceResponse)
def get_integration_plan(
    plan_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: FactoryIntegrationStore = Depends(get_factory_integration_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_plan(organization_id, plan_id))
    return _envelope("integration_plan", plan_id, value.content_fingerprint, value)


@router.get("/integration-receipts/{plan_fingerprint}", response_model=EvidenceResponse)
def get_integration_receipt(
    plan_fingerprint: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    store: FactoryIntegrationStore = Depends(get_factory_integration_store),
):
    _membership(runtime, user, organization_id)
    value = _found(store.get_receipt_for_plan(organization_id, plan_fingerprint))
    return _envelope(
        "integration_receipt", value.receipt_id, value.content_fingerprint, value
    )
