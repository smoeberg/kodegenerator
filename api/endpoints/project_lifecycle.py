"""PC-101 project lifecycle endpoints for the first-party Control Plane."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.endpoints.control_plane import _context, _project_response
from api.models import ControlPlaneIntentInput
from domain.project import (
    ProjectContractError,
    ProjectFingerprintError,
    ProjectIntent,
    ProjectStateError,
)
from infrastructure.persistence.repositories import RepositoryError
from runtime.commands import CommandConflictError
from runtime.core import CommandAuthorizationError, DORRuntime
from runtime.project_completion_evidence import (
    ProjectCompletionEvidence,
    ProjectCompletionEvidenceError,
)
from runtime.project_lifecycle_runtime import (
    ArchiveProjectCommand,
    CancelProjectCommand,
    CompleteProjectCommand,
    ContinueProjectCommand,
    ProjectLifecycleRuntime,
    RequestProjectCompletionCommand,
)
from runtime.project_runtime import ProjectNotFoundError

router = APIRouter(
    prefix="/api/v1/control-plane/projects",
    tags=["control-plane-v1"],
)


class CompletionRequestBody(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    expected_plan_request_fingerprint: str = Field(min_length=64, max_length=64)


class CompletionEvidenceBody(BaseModel):
    onboarding_intent_id: str = Field(min_length=1, max_length=128)
    repository_commit_sha: str = Field(min_length=40, max_length=40)
    delivery_certificate_id: str = Field(min_length=64, max_length=64)
    traceability_manifest_id: str = Field(min_length=64, max_length=64)
    integration_receipt_id: str = Field(min_length=64, max_length=64)


class CompleteProjectBody(CompletionRequestBody):
    evidence: CompletionEvidenceBody


class CancelProjectBody(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=2_000)


class ArchiveProjectBody(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    expected_revision: int = Field(ge=0)


class ContinueProjectBody(BaseModel):
    command_id: str = Field(min_length=1, max_length=128)
    organization_id: str = Field(min_length=1, max_length=128)
    expected_source_revision: int = Field(ge=0)
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=20_000)
    intent: ControlPlaneIntentInput


def _result_payload(result) -> dict[str, Any]:
    project = result.project
    public = _project_response(project).model_dump(mode="json")
    public.update(
        {
            "completion_requested_by": project.completion_requested_by,
            "completion_requested_at": (
                project.completion_requested_at.isoformat()
                if project.completion_requested_at is not None
                else None
            ),
            "completion_request_command_id": project.completion_request_command_id,
            "completion_record_id": project.completion_record_id,
            "completed_by": project.completed_by,
            "completed_at": (
                project.completed_at.isoformat() if project.completed_at is not None else None
            ),
            "cancelled_by": project.cancelled_by,
            "cancelled_at": (
                project.cancelled_at.isoformat() if project.cancelled_at is not None else None
            ),
            "cancel_command_id": project.cancel_command_id,
            "cancellation_reason": project.cancellation_reason,
            "archived_by": project.archived_by,
            "archived_at": (
                project.archived_at.isoformat() if project.archived_at is not None else None
            ),
            "archive_command_id": project.archive_command_id,
            "archived_from_status": (
                project.archived_from_status.value
                if project.archived_from_status is not None
                else None
            ),
            "continued_from_project_id": project.continued_from_project_id,
        }
    )
    return {
        "command_id": result.command_id,
        "replayed": result.replayed,
        "project": public,
    }


def _raise_lifecycle_error(exc: Exception) -> None:
    if isinstance(exc, CommandAuthorizationError):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "authorization_denied",
                "reason_code": exc.decision.reason_code,
            },
        ) from exc
    if isinstance(exc, ProjectNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found"},
        ) from exc
    if isinstance(exc, ProjectCompletionEvidenceError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "completion_evidence_rejected", "reason": str(exc)},
        ) from exc
    if isinstance(
        exc,
        (
            CommandConflictError,
            ProjectFingerprintError,
            ProjectStateError,
            RepositoryError,
            ProjectContractError,
        ),
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "project_lifecycle_conflict", "reason": str(exc)},
        ) from exc
    raise exc


@router.post("/{project_id}/completion/request", status_code=status.HTTP_202_ACCEPTED)
def request_project_completion(
    project_id: str,
    request: CompletionRequestBody,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = ProjectLifecycleRuntime(dor).request_completion(
            context,
            RequestProjectCompletionCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                project_id=project_id,
                expected_revision=request.expected_revision,
                expected_plan_request_fingerprint=request.expected_plan_request_fingerprint,
            ),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)
        raise
    return _result_payload(result)


@router.post("/{project_id}/completion/complete", status_code=status.HTTP_200_OK)
def complete_project(
    project_id: str,
    request: CompleteProjectBody,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = ProjectLifecycleRuntime(dor).complete_project(
            context,
            CompleteProjectCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                project_id=project_id,
                expected_revision=request.expected_revision,
                expected_plan_request_fingerprint=request.expected_plan_request_fingerprint,
                evidence=ProjectCompletionEvidence(
                    onboarding_intent_id=request.evidence.onboarding_intent_id,
                    repository_commit_sha=request.evidence.repository_commit_sha,
                    delivery_certificate_id=request.evidence.delivery_certificate_id,
                    traceability_manifest_id=request.evidence.traceability_manifest_id,
                    integration_receipt_id=request.evidence.integration_receipt_id,
                ),
            ),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)
        raise
    return _result_payload(result)


@router.post("/{project_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_project(
    project_id: str,
    request: CancelProjectBody,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = ProjectLifecycleRuntime(dor).cancel_project(
            context,
            CancelProjectCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                project_id=project_id,
                expected_revision=request.expected_revision,
                reason=request.reason,
            ),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)
        raise
    return _result_payload(result)


@router.post("/{project_id}/archive", status_code=status.HTTP_200_OK)
def archive_project(
    project_id: str,
    request: ArchiveProjectBody,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = ProjectLifecycleRuntime(dor).archive_project(
            context,
            ArchiveProjectCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                project_id=project_id,
                expected_revision=request.expected_revision,
            ),
        )
    except Exception as exc:
        _raise_lifecycle_error(exc)
        raise
    return _result_payload(result)


@router.post("/{project_id}/continue", status_code=status.HTTP_201_CREATED)
def continue_project(
    project_id: str,
    request: ContinueProjectBody,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> dict[str, Any]:
    context = _context(dor, current_user, request.organization_id)
    try:
        result = ProjectLifecycleRuntime(dor).continue_project(
            context,
            ContinueProjectCommand(
                command_id=request.command_id,
                organization_id=request.organization_id,
                source_project_id=project_id,
                expected_source_revision=request.expected_source_revision,
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
    except Exception as exc:
        _raise_lifecycle_error(exc)
        raise
    return _result_payload(result)


__all__ = ["router"]
