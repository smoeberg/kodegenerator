"""Phase 2 acceptance tests for the DOR command runtime.

These tests define the command boundary before implementation. They build on
Phase 1's public runtime API and verify authorization, idempotency, atomicity,
and event emission semantics.
"""

from pathlib import Path

import pytest

from domain.actor import Actor, ActorType
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from runtime.context import ContextError
from runtime.core import DORRuntime, NotFoundError


# Phase 2 implementation contract: the command runtime is expected to expose
# these public types from runtime.commands.
from runtime.commands import AdvanceWorkflowCommand, CommandConflictError


def _runtime(tmp_path: Path, name: str = "phase2") -> DORRuntime:
    return DORRuntime(f"sqlite:///{tmp_path / f'{name}.db'}")


def _context(
    runtime: DORRuntime,
    organization_id: str = "org-a",
    actor_id: str = "actor-a",
):
    organization = Organization(id=organization_id, name=organization_id)
    actor = Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id)
    runtime.create_organization(organization)
    runtime.register_actor(actor, organization_id)
    principal = Principal(
        id=actor_id,
        type="user",
        metadata={"actor_id": actor_id},
    )
    return runtime.establish_context(principal, organization_id, actor_id)


def test_command_executes_in_context(tmp_path: Path):
    runtime = _runtime(tmp_path)
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "commanded")

    result = runtime.execute_command(
        context,
        AdvanceWorkflowCommand(
            command_id="cmd-1",
            organization_id="org-a",
            workflow_id=workflow.id,
            target_state=WorkflowState.ANALYSIS,
        ),
    )

    assert result.command_id == "cmd-1"
    assert result.workflow.current_state.name == WorkflowState.ANALYSIS


def test_command_cannot_cross_organization(tmp_path: Path):
    runtime = _runtime(tmp_path, "isolation")
    runtime.boot()
    context_a = _context(runtime, "org-a", "actor-a")
    context_b = _context(runtime, "org-b", "actor-b")
    workflow_b = runtime.create_workflow(context_b, "private-b")

    with pytest.raises(NotFoundError):
        runtime.execute_command(
            context_a,
            AdvanceWorkflowCommand(
                command_id="cmd-cross-org",
                organization_id="org-a",
                workflow_id=workflow_b.id,
                target_state=WorkflowState.ANALYSIS,
            ),
        )


def test_command_is_idempotent(tmp_path: Path):
    runtime = _runtime(tmp_path, "idempotency")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "idempotent")
    command = AdvanceWorkflowCommand(
        command_id="cmd-idempotent",
        organization_id="org-a",
        workflow_id=workflow.id,
        target_state=WorkflowState.ANALYSIS,
    )

    first = runtime.execute_command(context, command)
    second = runtime.execute_command(context, command)

    assert second.command_id == first.command_id
    assert second.workflow.current_state.name == WorkflowState.ANALYSIS
    assert [event.event_type.name for event in runtime.get_events(context, workflow.id)] == [
        "WORKFLOW_CREATED",
        "WORKFLOW_STATE_CHANGED",
    ]


def test_command_failure_is_atomic(tmp_path: Path):
    runtime = _runtime(tmp_path, "atomic-failure")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "atomic")

    with pytest.raises(Exception):
        runtime.execute_command(
            context,
            AdvanceWorkflowCommand(
                command_id="cmd-invalid",
                organization_id="org-a",
                workflow_id=workflow.id,
                target_state=WorkflowState.RELEASED,
            ),
        )

    assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.NEW
    assert [event.event_type.name for event in runtime.get_events(context, workflow.id)] == [
        "WORKFLOW_CREATED",
    ]


def test_successful_command_emits_event(tmp_path: Path):
    runtime = _runtime(tmp_path, "events")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "events")

    runtime.execute_command(
        context,
        AdvanceWorkflowCommand(
            command_id="cmd-event",
            organization_id="org-a",
            workflow_id=workflow.id,
            target_state=WorkflowState.ANALYSIS,
        ),
    )

    events = runtime.get_events(context, workflow.id)
    assert len(events) == 2
    assert events[-1].event_type.name == "WORKFLOW_STATE_CHANGED"
    assert events[-1].organization_id == "org-a"
    assert events[-1].actor_id == "actor-a"


def test_event_and_state_commit_atomically(tmp_path: Path):
    runtime = _runtime(tmp_path, "atomic-commit")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "atomic-commit")

    command = AdvanceWorkflowCommand(
        command_id="cmd-atomic-commit",
        organization_id="org-a",
        workflow_id=workflow.id,
        target_state=WorkflowState.ANALYSIS,
    )
    runtime.execute_command(context, command)

    restarted = DORRuntime(f"sqlite:///{tmp_path / 'atomic-commit.db'}")
    restarted.boot()
    restarted_context = restarted.establish_context(
        Principal(id="actor-a", type="user", metadata={"actor_id": "actor-a"}),
        "org-a",
        "actor-a",
    )

    persisted = restarted.get_workflow(restarted_context, workflow.id)
    events = restarted.get_events(restarted_context, workflow.id)
    assert persisted.current_state.name == WorkflowState.ANALYSIS
    assert events[-1].event_type.name == "WORKFLOW_STATE_CHANGED"


def test_command_organization_must_match_context(tmp_path: Path):
    runtime = _runtime(tmp_path, "command-context")
    runtime.boot()
    context = _context(runtime, "org-a", "actor-a")
    workflow = runtime.create_workflow(context, "context")

    with pytest.raises(ContextError):
        runtime.execute_command(
            context,
            AdvanceWorkflowCommand(
                command_id="cmd-wrong-org",
                organization_id="org-b",
                workflow_id=workflow.id,
                target_state=WorkflowState.ANALYSIS,
            ),
        )


def test_reusing_command_id_for_different_payload_is_rejected(tmp_path: Path):
    runtime = _runtime(tmp_path, "command-conflict")
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "conflict")

    first = AdvanceWorkflowCommand(
        command_id="cmd-conflict",
        organization_id="org-a",
        workflow_id=workflow.id,
        target_state=WorkflowState.ANALYSIS,
    )
    second = AdvanceWorkflowCommand(
        command_id="cmd-conflict",
        organization_id="org-a",
        workflow_id=workflow.id,
        target_state=WorkflowState.DESIGN,
    )

    runtime.execute_command(context, first)
    with pytest.raises(CommandConflictError):
        runtime.execute_command(context, second)
