"""Versioned first-party Control Plane project API."""

from __future__ import annotations

from datetime import timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.models import (
    ControlPlaneActivateProjectScopeRequest,
    ControlPlaneCreateProjectRequest,
    ControlPlaneIntentResponse,
    ControlPlaneLaunchProjectRequest,
    ControlPlaneProjectCommandResponse,
    ControlPlaneProjectEventResponse,
    ControlPlaneProjectEventsResponse,
    ControlPlaneProjectResponse,
)
from domain.event import Event
from domain.principal import Principal
from domain.project import (
    Project,
    ProjectContractError,
    ProjectFingerprintError,
    ProjectIntent,
    ProjectStateError,
    fingerprint_event_payload,
)
from infrastructure.persistence.models import ProjectModel
from infrastructure.persistence.repositories import RepositoryError
from runtime.commands import CommandConflictError
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError
from runtime.project_runtime import (
    CreateProjectCommand,
    LaunchProjectCommand,
    ProjectNotFoundError,
)
from runtime.project_scope_runtime import (
    ActivateProjectScopeCommand,
    ProjectScopeNotFoundError,
    ProjectScopeRuntime,
)

router = APIRouter(
    prefix="/api/v1/control-plane/projects",
    tags=["control-plane-v1"],
)


def _context(dor: DORRuntime, current_user: User, organization_id: str):
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


def _project_response(project: Project) -> ControlPlaneProjectResponse:
    return ControlPlaneProjectResponse(
        project_id=project.id,
        organization_id=project.organization_id,
        name=project.name,
        description=project.description,
        status=project.status.value,
        project_fingerprint=project.fingerprint,
        intent=ControlPlaneIntentResponse(
            goal=project.intent.goal,
            description=project.intent.description,
            priority=project.intent.priority,
            constraints=project.intent.canonical_dict()["constraints"],
            required_capabilities=list(project.intent.required_capabilities),
            fingerprint=project.intent.fingerprint,
        ),
        created_by=project.created_by,
        created_at=project.created_at,
        updated_at=project.updated_at,
        launched_by=project.launched_by,
        launched_at=project.launched_at,
        launch_request_fingerprint=project.launch_request_fingerprint,
        launch_command_id=project.launch_command_id,
        active_plan_request_fingerprint=project.active_plan_request_fingerprint,
        active_scope_activated_by=project.active_scope_activated_by,
        active_scope_activated_at=project.active_scope_activated_at,
        active_scope_command_id=project.active_scope_command_id,
        completion_requested_by=project.completion_requested_by,
        completion_requested_at=project.completion_requested_at,
        completion_request_command_id=project.completion_request_command_id,
        completion_record_id=project.completion_record_id,
        completed_by=project.completed_by,
        completed_at=project.completed_at,
        cancelled_by=project.cancelled_by,
        cancelled_at=project.cancelled_at,
        cancel_command_id=project.cancel_command_id,
        cancellation_reason=project.cancellation_reason,
        archived_by=project.archived_by,
        archived_at=project.archived_at,
        archive_command_id=project.archive_command_id,
        archived_from_status=(
            project.archived_from_status.value
            if project.archived_from_status is not None
            else None
        ),
        continued_from_project_id=project.continued_from_project_id,
        revision=project.revision,
    )


def _event_response(event: Event) -> ControlPlaneProjectEventResponse:
    occurred_at = event.timestamp
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    occurred_at = occurred_at.astimezone(timezone.utc)
    public = {
        "contract_version": "1.0",
        "event_id": event.id,
        "event_type": event.event_type.name,
        "aggregate_id": event.aggregate_id or "",
        "organization_id": event.organization_id or "",
        "actor_id": event.actor_id,
        "occurred_at": occurred_at.isoformat(),
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "sequence": event.sequence,
        "metadata": event.metadata,
    }
    return ControlPlaneProjectEventResponse(
        event_id=event.id,
        event_type=event.event_type.name,
        aggregate_id=event.aggregate_id or "",
        organization_id=event.organization_id or "",
        actor_id=event.actor_id,
        occurred_at=occurred_at,
        correlation_id=event.correlation_id,
        causation_id=event.causation_id,
        sequence=event.sequence,
        metadata=event.metadata,
        event_fingerprint=fingerprint_event_payload(public),
    )


def _authorization_error(exc: CommandAuthorizationError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "authorization_denied",
            "reason_code": exc.decision.reason_code,
        },
    )


@router.get("")
def list_projects(
    organization_id: str | None = Query(default=None, min_length=1, max_length=128),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, object]:
    selected_organization_id = organization_id or current_user.organization_id
    if not selected_organization_id:
        return {"organization_id": None, "projects": []}

    context = _context(dor, current_user, selected_organization_id)
    with dor.database.session(selected_organization_id) as session:
        project_ids = list(
            session.scalars(
                select(ProjectModel.id)
                .where(ProjectModel.organization_id == selected_organization_id)
                .order_by(ProjectModel.updated_at.desc(), ProjectModel.id)
            ).all()
        )

    projects: list[ControlPlaneProjectResponse] = []
    for project_id in project_ids:
        try:
            project = dor.projects.get_project(context, str(project_id))
        except CommandAuthorizationError:
            continue
        except ProjectNotFoundError:
            continue
        except RepositoryError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "project_catalog_unavailable"},
            ) from exc
        projects.append(_project_response(project))

    return {"organization_id": selected_organization_id, "projects": projects}


@router.post(
    "",
    response_model=ControlPlaneProjectCommandResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    request: ControlPlaneCreateProjectRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ControlPlaneProjectCommandResponse:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = dor.projects.create_project(
            context,
            CreateProjectCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                name=request.name,
                description=request.description,
                intent=ProjectIntent(
                    goal=request.intent.goal,
                    description=request.intent.description,
                    priority=request.intent.priority,
                    constraints=request.intent.constraints,
                    required_capabilities=tuple(request.intent.required_capabilities),
                ),
            ),
        )
    except CommandAuthorizationError as exc:
        raise _authorization_error(exc) from exc
    except CommandConflictError as exc:
        raise HTTPException(status_code=409, detail={"error": "command_conflict"}) from exc
    except ProjectContractError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_project_contract", "reason": str(exc)}) from exc
    return ControlPlaneProjectCommandResponse(
        command_id=result.command_id,
        replayed=result.replayed,
        project=_project_response(result.project),
    )


@router.post(
    "/{project_id}/launch",
    response_model=ControlPlaneProjectCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def launch_project(
    project_id: str,
    request: ControlPlaneLaunchProjectRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ControlPlaneProjectCommandResponse:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = dor.projects.launch_project(
            context,
            LaunchProjectCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                project_id=project_id,
                expected_project_fingerprint=request.expected_project_fingerprint,
            ),
        )
    except CommandAuthorizationError as exc:
        raise _authorization_error(exc) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"}) from exc
    except ProjectContractError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_project_contract", "reason": str(exc)}) from exc
    except (CommandConflictError, ProjectFingerprintError, ProjectStateError, RepositoryError) as exc:
        raise HTTPException(status_code=409, detail={"error": "project_launch_conflict", "reason": str(exc)}) from exc
    return ControlPlaneProjectCommandResponse(
        command_id=result.command_id,
        replayed=result.replayed,
        project=_project_response(result.project),
    )


@router.post(
    "/{project_id}/scope/activate",
    response_model=ControlPlaneProjectCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def activate_project_scope(
    project_id: str,
    request: ControlPlaneActivateProjectScopeRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ControlPlaneProjectCommandResponse:
    """Atomically make one exact plan fingerprint the project's executable scope."""
    context = _context(dor, current_user, request.organization_id)
    try:
        result = ProjectScopeRuntime(dor).activate(
            context,
            ActivateProjectScopeCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                project_id=project_id,
                plan_request_fingerprint=request.plan_request_fingerprint,
                expected_revision=request.expected_revision,
            ),
        )
    except CommandAuthorizationError as exc:
        raise _authorization_error(exc) from exc
    except ProjectScopeNotFoundError as exc:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"}) from exc
    except ProjectContractError as exc:
        raise HTTPException(status_code=422, detail={"error": "invalid_project_scope", "reason": str(exc)}) from exc
    except (CommandConflictError, ProjectStateError, RepositoryError) as exc:
        raise HTTPException(status_code=409, detail={"error": "project_scope_conflict", "reason": str(exc)}) from exc
    return ControlPlaneProjectCommandResponse(
        command_id=result.command_id,
        replayed=result.replayed,
        project=_project_response(result.project),
    )


@router.get("/{project_id}", response_model=ControlPlaneProjectResponse)
def get_project(
    project_id: str,
    organization_id: str = Query(..., min_length=1, max_length=128),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ControlPlaneProjectResponse:
    context = _context(dor, current_user, organization_id)
    try:
        project = dor.projects.get_project(context, project_id)
    except CommandAuthorizationError as exc:
        raise _authorization_error(exc) from exc
    except (ProjectNotFoundError, RepositoryError) as exc:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"}) from exc
    return _project_response(project)


@router.get("/{project_id}/events", response_model=ControlPlaneProjectEventsResponse)
def get_project_events(
    project_id: str,
    organization_id: str = Query(..., min_length=1, max_length=128),
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
    include_authorization_audit: bool = Query(default=True),
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> ControlPlaneProjectEventsResponse:
    context = _context(dor, current_user, organization_id)
    try:
        events = dor.projects.get_events(
            context,
            project_id,
            after_sequence=after_sequence,
            limit=limit,
            include_authorization_audit=include_authorization_audit,
        )
    except CommandAuthorizationError as exc:
        raise _authorization_error(exc) from exc
    except (ProjectNotFoundError, RepositoryError) as exc:
        raise HTTPException(status_code=404, detail={"error": "project_not_found"}) from exc
    next_sequence = events[-1].sequence if events else after_sequence
    return ControlPlaneProjectEventsResponse(
        project_id=project_id,
        events=[_event_response(event) for event in events],
        next_after_sequence=next_sequence,
    )
