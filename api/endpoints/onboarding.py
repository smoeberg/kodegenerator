"""Versioned Control Plane API for governed onboarding-intent declarations."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.auth import User, get_current_active_user, require_user_organization
from api.dependencies import get_dor
from api.onboarding_contracts import (
    OnboardingIntentCommandResponse,
    OnboardingIntentDeclareRequest,
    OnboardingIntentResponse,
)
from domain.principal import Principal
from infrastructure.persistence.uow import UnitOfWork
from phase4.onboarding import OnboardingContractError, OnboardingIntent, OnboardingIntentDraft
from runtime.commands import CommandConflictError
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError
from runtime.onboarding_runtime import (
    DeclareOnboardingIntentCommand,
    OnboardingIntentConflictError,
    OnboardingIntentNotFoundError,
    OnboardingProjectNotFoundError,
    OnboardingRuntime,
)

router = APIRouter(
    prefix="/api/v1/control-plane/onboarding-intents",
    tags=["control-plane-onboarding-v1"],
)


def _intent_response(intent: OnboardingIntent) -> OnboardingIntentResponse:
    return OnboardingIntentResponse(
        intent_id=intent.intent_id,
        content_fingerprint=intent.content_fingerprint,
        organization_id=intent.organization_id,
        project_id=intent.project_id,
        source_repository=intent.source_repository,
        purpose=intent.purpose,
        rationale=intent.rationale,
        target_stack=intent.target_stack,
        supersedes_intent_id=intent.supersedes_intent_id,
        declared_by=intent.declared_by,
        declared_at=intent.declared_at,
    )


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


@router.get("/current", response_model=list[OnboardingIntentResponse])
def get_current_onboarding_intents(
    project_id: str = Query(min_length=1, max_length=128),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> list[OnboardingIntentResponse]:
    """Return current immutable onboarding intent leaves for one accessible project."""
    context = _context(dor, current_user)
    with dor.database.session(context.organization_id) as session:
        with UnitOfWork(session) as uow:
            project = uow.projects.get_for_organization(
                project_id,
                context.organization_id,
            )
            if project is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={"error": "project_not_found"},
                )
            intents = uow.onboarding_intents.get_current_for_project(
                project_id,
                context.organization_id,
            )
    return [_intent_response(intent) for intent in intents]


@router.post(
    "",
    response_model=OnboardingIntentCommandResponse,
    status_code=status.HTTP_201_CREATED,
)
def declare_onboarding_intent(
    request: OnboardingIntentDeclareRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> OnboardingIntentCommandResponse:
    """Declare one immutable onboarding intent through trusted Core authority."""
    context = _context(dor, current_user)
    try:
        draft = OnboardingIntentDraft(
            source_repository=request.source_repository,
            purpose=request.purpose,
            rationale=request.rationale,
            target_stack=request.target_stack,
            supersedes_intent_id=request.supersedes_intent_id,
        )
        result = OnboardingRuntime(dor).declare_intent(
            context,
            DeclareOnboardingIntentCommand(
                command_id=request.command_id,
                organization_id=context.organization_id,
                project_id=request.project_id,
                draft=draft,
            ),
        )
    except CommandAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "authorization_denied",
                "reason_code": exc.decision.reason_code,
                "capability_id": exc.decision.capability_id,
            },
        ) from exc
    except OnboardingProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found"},
        ) from exc
    except OnboardingIntentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "superseded_intent_not_found"},
        ) from exc
    except (CommandConflictError, OnboardingIntentConflictError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "onboarding_intent_conflict", "reason": str(exc)},
        ) from exc
    except (OnboardingContractError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_onboarding_intent", "reason": str(exc)},
        ) from exc

    return OnboardingIntentCommandResponse(
        command_id=result.command_id,
        replayed=result.replayed,
        intent=_intent_response(result.intent),
    )
