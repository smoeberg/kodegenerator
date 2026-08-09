"""Canonical API command for governed Implementation Agent proposals."""

from fastapi import APIRouter, Depends, HTTPException, status

from api.auth import User, get_current_active_user
from api.dependencies import (
    ImplementationAgentConfigurationError,
    get_dor,
    get_implementation_agent_runtime,
)
from api.models import (
    ImplementationProposalArtifactResponse,
    ImplementationProposalRequest,
    ImplementationProposalResponse,
)
from domain.principal import Principal
from phase4.context_packet import ContextItem
from phase4.implementation_agent import (
    IMPLEMENTATION_ACTION,
    ChangeBudget,
    ImplementationAgentAuthorityError,
    ImplementationAgentExecutionError,
    ImplementationAgentRun,
    ImplementationAgentRuntime,
    ImplementationCommandConflictError,
    ImplementationContextLimitError,
    ImplementationContractError,
)
from runtime.context import ContextError
from runtime.core import CommandAuthorizationError, DORRuntime, NotFoundError

router = APIRouter(prefix="/implementation-agent", tags=["implementation-agent"])


def _implementation_runtime() -> ImplementationAgentRuntime:
    try:
        return get_implementation_agent_runtime()
    except ImplementationAgentConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "implementation_agent_unavailable",
                "reason": str(exc),
            },
        ) from exc


def _response(
    command_id: str,
    run: ImplementationAgentRun,
) -> ImplementationProposalResponse:
    proposal = run.proposal
    return ImplementationProposalResponse(
        command_id=command_id,
        agent_identity=run.agent_identity,
        context_packet_id=run.context_packet.packet_id,
        request_fingerprint=run.request.request_fingerprint,
        authority_decision=run.authority.decision.value,
        authority_policy_id=run.authority.policy_id,
        authority_policy_version=run.authority.policy_version,
        execution_id=run.execution.execution_id,
        execution_status=run.execution.status.value,
        outcome_id=run.outcome.outcome_id,
        outcome_status=run.outcome.status.value,
        provenance_id=run.outcome.provenance_id,
        replayed=run.replayed,
        proposal=ImplementationProposalArtifactResponse(
            proposal_id=proposal.proposal_id,
            provider_id=proposal.provider_id,
            diff_sha256=proposal.diff_sha256,
            touched_paths=list(proposal.touched_paths),
            changed_lines=proposal.changed_lines,
            unified_diff=proposal.unified_diff,
        ),
    )


@router.post("/proposals", response_model=ImplementationProposalResponse)
def propose_patch(
    request: ImplementationProposalRequest,
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
    implementation_runtime: ImplementationAgentRuntime = Depends(
        _implementation_runtime
    ),
) -> ImplementationProposalResponse:
    """Authorize a human command, then execute the separately governed agent."""
    principal = Principal(
        id=current_user.username,
        type="user",
        metadata={"username": current_user.username},
    )
    try:
        context = dor.establish_context(
            principal=principal,
            organization_id=request.organization_id,
            actor_id=current_user.username,
        )
        dor.authority.require_capability(
            context,
            capability_id=IMPLEMENTATION_ACTION,
            command_id=request.command_id,
            command_type="ImplementationProposalCommand",
            resource_id=request.organization_id,
            resource_organization_id=request.organization_id,
            aggregate_type="implementation_request",
        )
    except CommandAuthorizationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "authorization_denied",
                "reason_code": exc.decision.reason_code,
                "reason": exc.decision.reason,
            },
        ) from exc
    except (ContextError, NotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "organization_context_denied"},
        ) from exc

    try:
        context_items = tuple(
            ContextItem(
                source=item.source,
                key=item.key,
                value=item.value,
                relevance=item.relevance,
                provenance=item.provenance,
                sensitivity=item.sensitivity,
            )
            for item in request.context_items
        )
        run = implementation_runtime.run(
            resource=request.resource,
            instruction=request.instruction,
            allowed_paths=tuple(request.allowed_paths),
            context_items=context_items,
            budget=ChangeBudget(
                max_files=request.max_files,
                max_changed_lines=request.max_changed_lines,
            ),
            idempotency_key=request.command_id,
        )
    except ImplementationAgentAuthorityError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "agent_authority_denied",
                "policy_id": exc.decision.policy_id,
            },
        ) from exc
    except ImplementationCommandConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "implementation_command_conflict"},
        ) from exc
    except (
        ImplementationContextLimitError,
        ImplementationContractError,
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "invalid_implementation_request", "reason": str(exc)},
        ) from exc
    except ImplementationAgentExecutionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"error": "implementation_provider_failed"},
        ) from exc
    return _response(request.command_id, run)
