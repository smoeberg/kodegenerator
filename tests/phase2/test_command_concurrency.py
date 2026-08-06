"""Concurrency acceptance tests for Phase 2 command idempotency."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from infrastructure.persistence.models import CommandExecutionModel
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import AdvanceWorkflowCommand
from runtime.core import DORRuntime


def _context(runtime: DORRuntime):
    organization = Organization(id="org-a", name="org-a")
    actor = Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a")
    runtime.create_organization(organization)
    runtime.register_actor(actor, "org-a")
    role = RoleDefinition(
        id="workflow.operator",
        name="Workflow Operator",
        capabilities=frozenset({"workflow.transition"}),
    )
    assignment = RoleAssignment(
        actor_id="actor-a",
        organization_id="org-a",
        role_definition_id=role.id,
    )
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)
    return runtime.establish_context(
        Principal(id="actor-a", type="user", metadata={"actor_id": "actor-a"}),
        "org-a",
        "actor-a",
    )


def test_concurrent_same_command_id_has_one_durable_receipt(tmp_path: Path):
    db = tmp_path / "concurrent.db"
    url = f"sqlite:///{db}"
    runtime = DORRuntime(url)
    runtime.boot()
    context = _context(runtime)
    workflow = runtime.create_workflow(context, "concurrent")
    command = AdvanceWorkflowCommand(
        command_id="cmd-concurrent",
        organization_id="org-a",
        workflow_id=workflow.id,
        target_state=WorkflowState.ANALYSIS,
    )

    def invoke():
        worker_context = runtime.establish_context(
            Principal(id="actor-a", type="user", metadata={"actor_id": "actor-a"}),
            "org-a",
            "actor-a",
        )
        return runtime.execute_command(worker_context, command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))

    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    with Session() as session:
        receipts = session.query(CommandExecutionModel).filter_by(command_id="cmd-concurrent").all()
        assert len(receipts) == 1

    assert all(result.command_id == "cmd-concurrent" for result in results)
    assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.ANALYSIS
