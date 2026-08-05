from __future__ import annotations

from datetime import datetime, timezone

from .commands import AdvanceWorkflowCommand, CommandConflictError, CommandResult
from .context import ContextError


def execute_command(runtime, context, command_request: AdvanceWorkflowCommand) -> CommandResult:
    """Execute an AdvanceWorkflowCommand using the runtime's UnitOfWork."""
    runtime._require_ready()
    if command_request.organization_id != context.organization_id:
        raise ContextError("Command organization does not match runtime context")

    with runtime.database.session() as session:
        with runtime._uow(session) as uow:
            existing = uow.commands.get(command_request.command_id)
            if existing is not None:
                if (
                    existing.organization_id != context.organization_id
                    or existing.actor_id != context.actor_id
                    or existing.command_type != type(command_request).__name__
                    or existing.payload != command_request.payload
                ):
                    raise CommandConflictError(
                        f"Command ID already used with different command data: {command_request.command_id}"
                    )
                workflow = uow.workflows.get_for_organization(command_request.workflow_id, context.organization_id)
                if workflow is None:
                    raise runtime.NotFoundError(f"Workflow not found: {command_request.workflow_id}")
                workflow.organization = context.organization
                return CommandResult(command_id=command_request.command_id, workflow=workflow)

            workflow = uow.workflows.get_for_organization(command_request.workflow_id, context.organization_id)
            if workflow is None:
                raise runtime.NotFoundError(f"Workflow not found: {command_request.workflow_id}")
            workflow.organization = context.organization
            revision = uow.workflows.get_revision(command_request.workflow_id, context.organization_id)
            if revision is None:
                raise runtime.NotFoundError(f"Workflow not found: {command_request.workflow_id}")

            events = workflow.transition_to(command_request.target_state, context.actor)
            for event in events:
                workflow.apply_event(event)
                uow.events.append(event)
            uow.workflows.update(workflow, context.organization_id, expected_revision=revision)
            uow.commands.add(
                command_id=command_request.command_id,
                organization_id=context.organization_id,
                actor_id=context.actor_id,
                command_type=type(command_request).__name__,
                payload=command_request.payload,
                aggregate_id=workflow.id,
                created_at=datetime.now(timezone.utc),
            )
            return CommandResult(command_id=command_request.command_id, workflow=workflow)
