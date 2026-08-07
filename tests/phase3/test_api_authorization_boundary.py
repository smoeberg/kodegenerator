"""P3-11 API boundary tests for workflow command authorization."""
from pathlib import Path
import pytest
from fastapi import HTTPException
from api.auth import User
from api.endpoints.workflows import transition_workflow_authorized
from api.models import WorkflowStateEnum, WorkflowTransitionRequest
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.organization import Organization
from domain.principal import Principal
from domain.workflow import WorkflowState
from infrastructure.persistence.uow import UnitOfWork
from runtime.core import DORRuntime


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'p3-11-api.db'}"); runtime.boot(); return runtime


def _context(runtime: DORRuntime, organization_id: str, actor_id: str):
    runtime.create_organization(Organization(id=organization_id, name=organization_id)); runtime.register_actor(Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id), organization_id)
    return runtime.establish_context(Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}), organization_id, actor_id)


def _grant_transition(runtime: DORRuntime, organization_id: str, actor_id: str) -> None:
    role_id = f"workflow.operator.{organization_id}.{actor_id}"
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(RoleDefinition(id=role_id, name="Workflow Operator", organization_id=organization_id, capabilities=frozenset({"workflow.transition"})))
            uow.authority.assign_role(RoleAssignment(actor_id=actor_id, organization_id=organization_id, role_definition_id=role_id))


def _user(actor_id: str) -> User:
    return User(username=actor_id, full_name=actor_id)


def test_authorized_api_command_uses_path_workflow_id(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime, "org-a", "actor-a"); _grant_transition(runtime, "org-a", "actor-a"); workflow = runtime.create_workflow(context, "protected")
    response = transition_workflow_authorized(workflow.id, WorkflowTransitionRequest(organization_id="org-a", command_id="api-command-1", new_state=WorkflowStateEnum.ANALYSIS), _user("actor-a"), runtime)
    assert response.id == workflow.id; assert response.current_state == WorkflowStateEnum.ANALYSIS


def test_unauthorized_api_command_is_denied_and_audited(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime, "org-a", "actor-a"); workflow = runtime.create_workflow(context, "protected")
    with pytest.raises(HTTPException) as exc:
        transition_workflow_authorized(workflow.id, WorkflowTransitionRequest(organization_id="org-a", command_id="api-denied-1", new_state=WorkflowStateEnum.ANALYSIS), _user("actor-a"), runtime)
    assert exc.value.status_code == 403; assert exc.value.detail["reason_code"] == "capability_not_granted"; assert runtime.get_workflow(context, workflow.id).current_state.name == WorkflowState.NEW


def test_api_cannot_substitute_workflow_id_from_request_body(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path); context = _context(runtime, "org-a", "actor-a"); _grant_transition(runtime, "org-a", "actor-a"); workflow_a = runtime.create_workflow(context, "workflow-a"); workflow_b = runtime.create_workflow(context, "workflow-b")
    response = transition_workflow_authorized(workflow_a.id, WorkflowTransitionRequest(organization_id="org-a", command_id="api-path-authority", new_state=WorkflowStateEnum.ANALYSIS), _user("actor-a"), runtime)
    assert response.id == workflow_a.id; assert runtime.get_workflow(context, workflow_a.id).current_state.name == WorkflowState.ANALYSIS; assert runtime.get_workflow(context, workflow_b.id).current_state.name == WorkflowState.NEW
