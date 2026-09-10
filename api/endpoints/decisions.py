"""Canonical Decision Engine API endpoints."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.auth import User, get_current_active_user, require_user_organization
from api.dependencies import get_dor
from domain.decision import (
    AgentVote,
    Decision,
    DecisionAlternative,
    DecisionCategory,
    RiskLevel,
)
from domain.principal import Principal
from infrastructure.persistence.uow import UnitOfWork
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError
from services.decision_gate_service import DecisionGateError, DecisionGateService, DecisionNotFoundError


router = APIRouter(prefix="/api/v1/decisions", tags=["decisions"])
_service = DecisionGateService()


class CreateDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1, max_length=256)
    category: DecisionCategory
    question: str = Field(min_length=1, max_length=8000)
    alternatives: list[DecisionAlternative] = Field(min_length=2)
    agent_votes: list[AgentVote] = Field(default_factory=list)
    provenance_id: str = Field(min_length=1, max_length=256)
    risk_level: RiskLevel = RiskLevel.MEDIUM


class ResolveDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_alternative: str = Field(min_length=1, max_length=32)
    rationale: str = Field(min_length=1, max_length=8000)


class DecisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    decision: Decision


def _context(dor: DORRuntime, current_user: User):
    organization_id = require_user_organization(current_user)
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"actor_id": current_user.username},
    )
    try:
        return dor.establish_context(
            principal=principal,
            organization_id=organization_id,
            actor_id=current_user.username,
        )
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_context_denied"},
        ) from exc


def _project_is_visible(dor: DORRuntime, organization_id: str, project_id: str) -> bool:
    with dor.database.session(organization_id) as session:
        with UnitOfWork(session) as uow:
            return (
                uow.projects.get_for_organization(project_id, organization_id)
                is not None
            )


def _require_project(dor: DORRuntime, current_user: User, project_id: str) -> str:
    context = _context(dor, current_user)
    if not _project_is_visible(dor, context.organization_id, project_id):
        # Do not disclose whether a project exists in another tenant.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="project_not_found",
        )
    return context.organization_id


def _require_decision(
    dor: DORRuntime,
    current_user: User,
    decision_id: str,
) -> Decision:
    try:
        decision = _service.get(decision_id)
    except DecisionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="decision_not_found",
        ) from exc
    _require_project(dor, current_user, decision.project_id)
    return decision


@router.post("", response_model=DecisionResponse, status_code=status.HTTP_201_CREATED)
def create_decision(
    request: CreateDecisionRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> DecisionResponse:
    _require_project(dor, current_user, request.project_id)
    decision = _service.create(Decision(**request.model_dump()))
    return DecisionResponse(decision=decision)


@router.get("/pending", response_model=list[Decision])
def get_pending_decisions(
    project_id: Optional[str] = Query(default=None, min_length=1, max_length=256),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> list[Decision]:
    context = _context(dor, current_user)
    if project_id is not None:
        _require_project(dor, current_user, project_id)
        return _service.pending(project_id=project_id)

    # Preserve the existing unfiltered endpoint contract without leaking decisions
    # across tenant boundaries. Filtering happens server-side, never in the GUI.
    return [
        decision
        for decision in _service.pending()
        if _project_is_visible(dor, context.organization_id, decision.project_id)
    ]


@router.get("/{decision_id}", response_model=Decision)
def get_decision(
    decision_id: str,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> Decision:
    return _require_decision(dor, current_user, decision_id)


@router.post("/{decision_id}/resolve", response_model=Decision)
def resolve_decision(
    decision_id: str,
    request: ResolveDecisionRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> Decision:
    _require_decision(dor, current_user, decision_id)
    try:
        return _service.resolve_human(
            decision_id,
            selected_alternative=request.selected_alternative,
            rationale=request.rationale,
            decided_by=current_user.username,
        )
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="decision_not_found") from exc
    except (DecisionGateError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
