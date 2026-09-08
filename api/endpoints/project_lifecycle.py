"""PC-101 project lifecycle endpoints for the first-party Control Plane."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.endpoints.control_plane import _context, _project_response
from domain.project import ProjectContractError, ProjectFingerprintError, ProjectStateError
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


def _result_payload(result) -> dict[str, Any]:
    return {
        "command_id": result.command_id,
        "replayed": result.replayed,
        "project": _project_response(result.project).model_dump(mode="json"),
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


__all__ = ["router"]
