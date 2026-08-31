"""Governed API for deterministic bot selection and frozen assignments."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import User, get_current_active_user
from api.dependencies import get_council_selection_service, get_dor
from api.schemas.bot_governance import SelectionCreateRequest, SelectionResponse
from domain.principal import Principal
from infrastructure.persistence.selection_store import CouncilSelectionConflictError
from phase4.verification.allocation_selector import (
    CouncilRunSelection,
    CouncilSelectionError,
    SelectionRequestContext,
)
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError
from services.council_selection import CouncilSelectionService

router = APIRouter(prefix="/api/v1/bot-selections", tags=["bot-selections"])
OVERRIDE_CAPABILITY = "bot_selection.override"


def _context(runtime: DORRuntime, user: User, organization_id: str):
    return runtime.establish_context(
        principal=Principal(
            id=user.username,
            type="user",
            metadata={"username": user.username},
        ),
        organization_id=organization_id,
        actor_id=user.username,
    )


def _authorize(
    runtime: DORRuntime,
    user: User,
    organization_id: str,
    command_id: str,
    run_id: str,
) -> None:
    try:
        context = _context(runtime, user, organization_id)
        runtime.authority.require_capability(
            context,
            capability_id=OVERRIDE_CAPABILITY,
            command_id=command_id,
            command_type="BotSelectionCommand",
            resource_id=run_id,
            resource_organization_id=organization_id,
            aggregate_type="bot_selection",
        )
    except CommandAuthorizationError as exc:
        raise HTTPException(
            status_code=403,
            detail={"error": "authorization_denied", "reason": exc.decision.reason},
        ) from exc
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=403, detail={"error": "organization_context_denied"}
        ) from exc


def _membership(runtime: DORRuntime, user: User, organization_id: str) -> None:
    try:
        _context(runtime, user, organization_id)
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=403, detail={"error": "organization_context_denied"}
        ) from exc


def _response(value: CouncilRunSelection) -> SelectionResponse:
    return SelectionResponse(
        run_id=value.run_id,
        decision_id=value.fingerprint,
        organization_id=value.organization_id,
        template_id=value.template_id,
        template_version=value.template_version,
        template_fingerprint=value.template_fingerprint,
        context_fingerprint=value.context_fingerprint,
        scope_id=value.scope_id,
        repository=value.repository,
        base_sha=value.base_sha,
        input_fingerprint=value.input_fingerprint,
        assignments=[assignment.__dict__ for assignment in value.assignments],
        receipts=[receipt.__dict__ for receipt in value.receipts],
        selector_version=value.selector_version,
        status=value.status,
        rationale=value.rationale,
        fingerprint=value.fingerprint,
        created_at=value.created_at,
    )


@router.post("", response_model=SelectionResponse, status_code=status.HTTP_201_CREATED)
def create_selection(
    request: SelectionCreateRequest,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: CouncilSelectionService = Depends(get_council_selection_service),
):
    _authorize(runtime, user, organization_id, request.command_id, request.run_id)
    refs = tuple(sorted(set(request.allocation_refs)))
    if len(refs) != len(request.allocation_refs):
        raise HTTPException(status_code=422, detail={"error": "duplicate_allocation"})
    try:
        template = service.get_template(
            organization_id, request.template_id, request.template_version
        )
        if template is None:
            raise CouncilSelectionError("Council template version does not exist")
        context = SelectionRequestContext(
            organization_id=organization_id,
            scope_id=request.scope_id,
            repository=request.repository,
            base_sha=request.base_sha,
            requirements_fingerprint=request.requirements_fingerprint,
            architecture_fingerprint=request.architecture_fingerprint,
            contract_fingerprint=request.contract_fingerprint,
            input_fingerprint=request.input_fingerprint,
            template_fingerprint=template.fingerprint,
        )
        value = service.select_and_freeze(
            organization_id=organization_id,
            run_id=request.run_id,
            template_id=request.template_id,
            template_version=request.template_version,
            allocation_refs=refs,
            context=context,
        )
        if value.status == "blocked":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "NO_ELIGIBLE_BOT",
                    "run_id": value.run_id,
                    "decision_fingerprint": value.fingerprint,
                    "reason": value.rationale,
                },
            )
        return _response(value)
    except CouncilSelectionConflictError as exc:
        raise HTTPException(
            status_code=409, detail={"error": "frozen_conflict"}
        ) from exc
    except (CouncilSelectionError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail={"error": "NO_ELIGIBLE_BOT", "reason": str(exc)},
        ) from exc


@router.get("/{run_id}", response_model=SelectionResponse)
def get_selection(
    run_id: str,
    organization_id: str = Query(...),
    user: User = Depends(get_current_active_user),
    runtime: DORRuntime = Depends(get_dor),
    service: CouncilSelectionService = Depends(get_council_selection_service),
):
    _membership(runtime, user, organization_id)
    value = service.get(organization_id, run_id)
    if value is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return _response(value)
