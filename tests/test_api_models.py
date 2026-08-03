"""Contract tests for the public DOR API models."""

from api.models import (
    ActorCreate,
    ActorTypeEnum,
    ArtifactCreate,
    ArtifactStateEnum,
    ArtifactTypeEnum,
    CapabilityCreate,
    IntentCreate,
    OrganizationCreate,
    RoleDefinitionCreate,
    TaskCreate,
    TaskStatusEnum,
    WorkflowCreate,
)


def test_actor_create_defaults_are_safe():
    actor = ActorCreate(id="actor-1", type=ActorTypeEnum.SERVICE, identity="svc")
    assert actor.status == "active"
    assert actor.capabilities == []


def test_organization_contract():
    organization = OrganizationCreate(id="org-1", name="EIRA")
    assert organization.id == "org-1"
    assert organization.description is None


def test_role_and_capability_contracts():
    role = RoleDefinitionCreate(id="role-1", name="Architect")
    capability = CapabilityCreate(id="cap-1", name="architecture")
    assert role.capabilities == []
    assert capability.level.value == "beginner"


def test_intent_contract_requires_creator_and_organization():
    intent = IntentCreate(
        id="intent-1",
        goal="Build DOR",
        creator_id="actor-1",
        organization_id="org-1",
    )
    assert intent.required_capabilities == []
    assert intent.constraints == {}


def test_workflow_task_and_artifact_contracts():
    workflow = WorkflowCreate(id="wf-1", name="Build")
    task = TaskCreate(id="task-1", name="Implement", workflow_id="wf-1")
    artifact = ArtifactCreate(
        id="artifact-1",
        version="1.0.0",
        artifact_type=ArtifactTypeEnum.IMPLEMENTATION,
        owner_id="actor-1",
        workflow_id="wf-1",
        metadata={"path": "src/example.py"},
    )

    assert workflow.current_state is None
    assert task.status is TaskStatusEnum.PENDING
    assert artifact.state is ArtifactStateEnum.DRAFT
    assert artifact.hash == ""
