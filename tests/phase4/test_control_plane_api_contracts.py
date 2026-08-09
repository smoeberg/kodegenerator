"""Adversarial and integration tests for Control Plane Core API v1."""

from __future__ import annotations

import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import update

os.environ.setdefault("DOR_JWT_SECRET_KEY", "control-plane-test-secret")

from api.auth import User
from api.endpoints.control_plane import (
    create_project as api_create_project,
)
from api.endpoints.control_plane import (
    get_project as api_get_project,
)
from api.endpoints.control_plane import (
    get_project_events as api_get_project_events,
)
from api.endpoints.control_plane import (
    launch_project as api_launch_project,
)
from api.models import (
    ControlPlaneCreateProjectRequest,
    ControlPlaneLaunchProjectRequest,
)
from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.event import EventType
from domain.organization import Organization
from domain.principal import Principal
from domain.project import (
    ProjectContractError,
    ProjectIntent,
    ProjectStatus,
)
from infrastructure.persistence.models import CommandExecutionModel, ProjectModel
from infrastructure.persistence.uow import UnitOfWork
from runtime.commands import CommandConflictError
from runtime.core import CommandAuthorizationError, DORRuntime
from runtime.project_runtime import (
    PROJECT_CREATE_ACTION,
    PROJECT_LAUNCH_ACTION,
    PROJECT_READ_ACTION,
    CreateProjectCommand,
    LaunchProjectCommand,
)


def _runtime(tmp_path: Path, name: str = "control-plane") -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / f'{name}.db'}")
    runtime.boot()
    runtime.create_organization(Organization(id="org-a", name="org-a"))
    runtime.register_actor(
        Actor(id="actor-a", type=ActorType.HUMAN, identity="actor-a"),
        "org-a",
    )
    return runtime


def _context(
    runtime: DORRuntime, organization_id: str = "org-a", actor_id: str = "actor-a"
):
    return runtime.establish_context(
        Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}),
        organization_id,
        actor_id,
    )


def _grant(runtime: DORRuntime, *capabilities: str) -> None:
    role = RoleDefinition(
        id="control-plane.operator",
        name="Control Plane Operator",
        organization_id="org-a",
        capabilities=frozenset(capabilities),
    )
    assignment = RoleAssignment(
        actor_id="actor-a",
        organization_id="org-a",
        role_definition_id=role.id,
        created_at=datetime.now(timezone.utc),
    )
    with runtime.database.session() as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)


def _intent(**overrides) -> ProjectIntent:
    values = {
        "goal": "Build a governed inventory service",
        "description": "Create the service without bypassing verification.",
        "priority": "high",
        "constraints": {"region": "eu", "replicas": 2},
        "required_capabilities": ("implementation.propose",),
    }
    values.update(overrides)
    return ProjectIntent(**values)


def _create_command(**overrides) -> CreateProjectCommand:
    values = {
        "command_id": "project-create-1",
        "organization_id": "org-a",
        "name": "Inventory Service",
        "description": "First governed project",
        "intent": _intent(),
    }
    values.update(overrides)
    return CreateProjectCommand(**values)


def _request(**overrides) -> ControlPlaneCreateProjectRequest:
    values = {
        "organization_id": "org-a",
        "command_id": "project-create-api-1",
        "name": "Inventory Service",
        "description": "First governed project",
        "intent": _intent().canonical_dict(),
    }
    values.update(overrides)
    return ControlPlaneCreateProjectRequest(**values)


def _user() -> User:
    return User(username="actor-a", full_name="Actor A")


def test_intent_fingerprint_is_canonical_and_rejects_ambiguous_json() -> None:
    left = _intent(constraints={"b": [2, 1], "a": {"enabled": True}})
    right = _intent(constraints={"a": {"enabled": True}, "b": [2, 1]})

    assert left.fingerprint == right.fingerprint
    with pytest.raises(ProjectContractError, match="non-finite"):
        _intent(constraints={"limit": math.inf})
    with pytest.raises(ProjectContractError, match="non-JSON"):
        _intent(constraints={"unsafe": object()})
    with pytest.raises(TypeError):
        left.constraints["a"] = False  # type: ignore[index]
    with pytest.raises(ProjectContractError, match="trimmed"):
        _create_command(command_id=" untrimmed")
    with pytest.raises(ProjectContractError, match="lowercase SHA-256"):
        LaunchProjectCommand(
            command_id="launch-invalid",
            organization_id="org-a",
            project_id="project-a",
            expected_project_fingerprint="invalid",
        )


def test_create_and_launch_are_atomic_persistent_and_audited(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_LAUNCH_ACTION, PROJECT_READ_ACTION)
    context = _context(runtime)

    created = runtime.projects.create_project(context, _create_command())
    launched = runtime.projects.launch_project(
        context,
        LaunchProjectCommand(
            command_id="project-launch-1",
            organization_id="org-a",
            project_id=created.project.id,
            expected_project_fingerprint=created.project.fingerprint,
        ),
    )

    assert created.replayed is False
    assert launched.project.status is ProjectStatus.LAUNCH_REQUESTED
    assert launched.project.fingerprint == created.project.fingerprint
    assert launched.project.launch_request_fingerprint
    assert launched.project.launch_command_id == "project-launch-1"
    events = runtime.projects.get_events(context, created.project.id)
    assert [event.event_type for event in events] == [
        EventType.AUTHORIZATION_GRANTED,
        EventType.PROJECT_CREATED,
        EventType.AUTHORIZATION_GRANTED,
        EventType.PROJECT_LAUNCH_REQUESTED,
    ]
    assert events[-1].metadata["execution_started"] is False
    assert events[-1].correlation_id == "project-launch-1"

    restarted = DORRuntime(runtime.database_url)
    restarted.boot()
    persisted = restarted.projects.get_project(
        _context(restarted),
        created.project.id,
    )
    assert persisted.status is ProjectStatus.LAUNCH_REQUESTED
    assert (
        persisted.launch_request_fingerprint
        == launched.project.launch_request_fingerprint
    )


def test_exact_command_replay_emits_no_new_events(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_LAUNCH_ACTION, PROJECT_READ_ACTION)
    context = _context(runtime)
    command = _create_command()

    first = runtime.projects.create_project(context, command)
    second = runtime.projects.create_project(context, command)
    launch = LaunchProjectCommand(
        command_id="project-launch-replay",
        organization_id="org-a",
        project_id=first.project.id,
        expected_project_fingerprint=first.project.fingerprint,
    )
    first_launch = runtime.projects.launch_project(context, launch)
    second_launch = runtime.projects.launch_project(context, launch)

    assert second.replayed is True
    assert second.project.id == first.project.id
    assert first_launch.replayed is False
    assert second_launch.replayed is True
    assert len(runtime.projects.get_events(context, first.project.id)) == 4


def test_concurrent_create_has_one_project_receipt_and_event_pair(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_READ_ACTION)
    command = _create_command(command_id="project-create-concurrent")

    def invoke():
        return runtime.projects.create_project(_context(runtime), command)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: invoke(), range(2)))

    assert {result.project.id for result in results} == {command.project_id}
    assert sorted(result.replayed for result in results) == [False, True]
    with runtime.database.session() as session:
        receipts = (
            session.query(CommandExecutionModel)
            .filter_by(command_id=command.command_id)
            .all()
        )
    assert len(receipts) == 1
    assert len(runtime.projects.get_events(_context(runtime), command.project_id)) == 2


def test_command_id_cannot_be_rebound(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION)
    context = _context(runtime)
    runtime.projects.create_project(context, _create_command())

    with pytest.raises(CommandConflictError):
        runtime.projects.create_project(
            context,
            _create_command(name="Substituted Project"),
        )


def test_create_denial_is_audited_without_project_mutation(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    context = _context(runtime)
    command = _create_command()

    with pytest.raises(CommandAuthorizationError) as exc_info:
        runtime.projects.create_project(context, command)

    assert exc_info.value.decision.reason_code == "capability_not_granted"
    with runtime.database.session() as session:
        uow = UnitOfWork(session)
        assert uow.projects.get_for_organization(command.project_id, "org-a") is None
        events = uow.events.for_aggregate(command.project_id, "org-a")
    assert [event.event_type for event in events] == [EventType.AUTHORIZATION_DENIED]


def test_launch_denial_does_not_change_created_project(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_READ_ACTION)
    context = _context(runtime)
    created = runtime.projects.create_project(context, _create_command()).project

    with pytest.raises(CommandAuthorizationError):
        runtime.projects.launch_project(
            context,
            LaunchProjectCommand(
                command_id="launch-denied",
                organization_id="org-a",
                project_id=created.id,
                expected_project_fingerprint=created.fingerprint,
            ),
        )

    persisted = runtime.projects.get_project(context, created.id)
    assert persisted.status is ProjectStatus.CREATED
    events = runtime.projects.get_events(context, created.id)
    assert events[-1].event_type is EventType.AUTHORIZATION_DENIED
    assert not any(
        event.event_type is EventType.PROJECT_LAUNCH_REQUESTED for event in events
    )


def test_stale_fingerprint_and_second_launch_fail_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_LAUNCH_ACTION, PROJECT_READ_ACTION)
    context = _context(runtime)
    created = runtime.projects.create_project(context, _create_command()).project

    with pytest.raises(Exception, match="fingerprint"):
        runtime.projects.launch_project(
            context,
            LaunchProjectCommand(
                command_id="launch-stale",
                organization_id="org-a",
                project_id=created.id,
                expected_project_fingerprint="0" * 64,
            ),
        )
    assert len(runtime.projects.get_events(context, created.id)) == 2

    runtime.projects.launch_project(
        context,
        LaunchProjectCommand(
            command_id="launch-first",
            organization_id="org-a",
            project_id=created.id,
            expected_project_fingerprint=created.fingerprint,
        ),
    )
    with pytest.raises(Exception, match="created state"):
        runtime.projects.launch_project(
            context,
            LaunchProjectCommand(
                command_id="launch-second",
                organization_id="org-a",
                project_id=created.id,
                expected_project_fingerprint=created.fingerprint,
            ),
        )
    assert len(runtime.projects.get_events(context, created.id)) == 4


def test_persisted_fingerprint_tampering_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_READ_ACTION)
    context = _context(runtime)
    created = runtime.projects.create_project(context, _create_command()).project

    with runtime.database.session() as session:
        session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == created.id)
            .values(project_fingerprint="0" * 64)
        )
        session.commit()

    with pytest.raises(Exception, match="fingerprint mismatch"):
        runtime.projects.get_project(context, created.id)


def test_launch_provenance_tampering_fails_closed(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_LAUNCH_ACTION, PROJECT_READ_ACTION)
    context = _context(runtime)
    created = runtime.projects.create_project(context, _create_command()).project
    runtime.projects.launch_project(
        context,
        LaunchProjectCommand(
            command_id="launch-provenance",
            organization_id="org-a",
            project_id=created.id,
            expected_project_fingerprint=created.fingerprint,
        ),
    )

    with runtime.database.session() as session:
        session.execute(
            update(ProjectModel)
            .where(ProjectModel.id == created.id)
            .values(launch_request_fingerprint="0" * 64)
        )
        session.commit()

    with pytest.raises(Exception, match="does not match project provenance"):
        runtime.projects.get_project(context, created.id)


def test_cross_organization_query_does_not_disclose_project(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_READ_ACTION)
    created = runtime.projects.create_project(
        _context(runtime),
        _create_command(),
    ).project
    runtime.create_organization(Organization(id="org-b", name="org-b"))
    runtime.register_actor(
        Actor(id="actor-b", type=ActorType.HUMAN, identity="actor-b"),
        "org-b",
    )

    with pytest.raises(CommandAuthorizationError) as exc_info:
        runtime.projects.get_project(_context(runtime, "org-b", "actor-b"), created.id)

    assert exc_info.value.decision.reason_code == "resource_not_accessible"


def test_api_v1_create_launch_query_and_event_cursor(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_LAUNCH_ACTION, PROJECT_READ_ACTION)

    created = api_create_project(_request(), _user(), runtime)
    launched = api_launch_project(
        created.project.project_id,
        ControlPlaneLaunchProjectRequest(
            organization_id="org-a",
            command_id="project-launch-api-1",
            expected_project_fingerprint=created.project.project_fingerprint,
        ),
        _user(),
        runtime,
    )
    queried = api_get_project(created.project.project_id, "org-a", _user(), runtime)
    events = api_get_project_events(
        created.project.project_id,
        "org-a",
        2,
        2,
        True,
        _user(),
        runtime,
    )

    assert created.contract_version == "1.0"
    assert created.execution_started is False
    assert launched.project.status == "launch_requested"
    assert queried.project_fingerprint == created.project.project_fingerprint
    assert [event.sequence for event in events.events] == [3, 4]
    assert events.next_after_sequence == 4
    assert all(len(event.event_fingerprint) == 64 for event in events.events)


def test_api_maps_denial_conflict_and_missing_to_non_disclosing_errors(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)

    with pytest.raises(HTTPException) as denied:
        api_create_project(_request(), _user(), runtime)
    assert denied.value.status_code == 403
    assert denied.value.detail["error"] == "authorization_denied"

    _grant(runtime, PROJECT_CREATE_ACTION, PROJECT_LAUNCH_ACTION, PROJECT_READ_ACTION)
    created = api_create_project(
        _request(command_id="create-api-errors"), _user(), runtime
    )
    with pytest.raises(HTTPException) as conflict:
        api_create_project(
            _request(command_id="create-api-errors", name="Changed"),
            _user(),
            runtime,
        )
    assert conflict.value.status_code == 409

    with pytest.raises(HTTPException) as missing:
        api_launch_project(
            "missing-project",
            ControlPlaneLaunchProjectRequest(
                organization_id="org-a",
                command_id="launch-missing",
                expected_project_fingerprint="0" * 64,
            ),
            _user(),
            runtime,
        )
    assert missing.value.status_code == 403
    assert missing.value.detail["error"] == "authorization_denied"
    assert created.project.status == "created"
