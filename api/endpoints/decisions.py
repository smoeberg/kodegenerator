"""Canonical Decision Engine API endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from api.auth import User, get_current_active_user
from domain.decision import (
    AgentVote,
    Decision,
    DecisionAlternative,
    DecisionCategory,
    DecisionStatus,
    RiskLevel,
)
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


@router.post("", response_model=DecisionResponse, status_code=status.HTTP_201_CREATED)
def create_decision(
    request: CreateDecisionRequest,
    _: User = Depends(get_current_active_user),
) -> DecisionResponse:
    decision = _service.create(Decision(**request.model_dump()))
    return DecisionResponse(decision=decision)


@router.get("/pending", response_model=list[Decision])
def get_pending_decisions(
    project_id: Optional[str] = Query(default=None, min_length=1, max_length=256),
    _: User = Depends(get_current_active_user),
) -> list[Decision]:
    return _service.pending(project_id=project_id)


@router.get("/{decision_id}", response_model=Decision)
def get_decision(
    decision_id: str,
    _: User = Depends(get_current_active_user),
) -> Decision:
    try:
        return _service.get(decision_id)
    except DecisionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="decision_not_found") from exc


@router.post("/{decision_id}/resolve", response_model=Decision)
def resolve_decision(
    decision_id: str,
    request: ResolveDecisionRequest,
    current_user: User = Depends(get_current_active_user),
) -> Decision:
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
