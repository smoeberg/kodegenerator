from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base, ProjectModel
from infrastructure.persistence.swarm_control_models import (
    SwarmDispatchControlModel,
    SwarmProjectDispatchModel,
)
from services.swarm_control_store import (
    SwarmControlStore,
    SwarmProjectConflictError,
)


def _store(tmp_path):
    database = tmp_path / "swarm-control.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(
        engine,
        tables=[
            ProjectModel.__table__,
            SwarmProjectDispatchModel.__table__,
            SwarmDispatchControlModel.__table__,
        ],
    )
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    return SwarmControlStore(sessions), sessions


def _project(sessions, *, project_id: str, organization_id: str, owner: str) -> None:
    now = datetime.now(timezone.utc)
    with sessions() as session:
        session.add(
            ProjectModel(
                id=project_id,
                organization_id=organization_id,
                name=project_id,
                description="",
                status="created",
                contract_version="1.0",
                intent={
                    "goal": "test",
                    "description": "",
                    "priority": "medium",
                    "constraints": {},
                    "required_capabilities": [],
                },
                intent_fingerprint="a" * 64,
                project_fingerprint="b" * 64,
                created_by=owner,
                created_at=now,
                updated_at=now,
                revision=0,
            )
        )
        session.commit()


def test_dispatch_registration_survives_store_restart(tmp_path) -> None:
    first, sessions = _store(tmp_path)
    _project(sessions, project_id="project-a", organization_id="org-a", owner="alice")

    dispatch, created = first.register_project(
        organization_id="org-a",
        project_id="project-a",
        owner_id="alice",
        requirements={"goal": "build"},
    )
    restarted = SwarmControlStore(sessions)

    assert created is True
    assert dispatch.project_id == "project-a"
    assert restarted.require_owner("org-a", "project-a", "alice") == dispatch


def test_dispatch_registration_is_idempotent_and_immutable(tmp_path) -> None:
    store, sessions = _store(tmp_path)
    _project(sessions, project_id="project-a", organization_id="org-a", owner="alice")
    request = dict(
        organization_id="org-a",
        project_id="project-a",
        owner_id="alice",
        requirements={"goal": "build"},
    )
    store.register_project(**request)

    _, created = store.register_project(**request)
    assert created is False
    with pytest.raises(SwarmProjectConflictError):
        store.register_project(**{**request, "requirements": {"goal": "changed"}})


def test_project_and_pause_state_are_tenant_isolated(tmp_path) -> None:
    store, sessions = _store(tmp_path)
    _project(sessions, project_id="project-a", organization_id="org-a", owner="alice")
    _project(sessions, project_id="project-b", organization_id="org-b", owner="bob")
    store.register_project(
        organization_id="org-a",
        project_id="project-a",
        owner_id="alice",
        requirements={},
    )
    store.register_project(
        organization_id="org-b",
        project_id="project-b",
        owner_id="bob",
        requirements={},
    )
    store.set_paused("org-a", paused=True, actor_id="alice")

    assert store.is_paused("org-a") is True
    assert store.is_paused("org-b") is False
    assert store.get_project("org-b", "project-a") is None
    with pytest.raises(PermissionError):
        store.require_owner("org-a", "project-a", "bob")


def test_non_owner_cannot_register_canonical_project(tmp_path) -> None:
    store, sessions = _store(tmp_path)
    _project(sessions, project_id="project-a", organization_id="org-a", owner="alice")

    with pytest.raises(KeyError):
        store.register_project(
            organization_id="org-a",
            project_id="project-a",
            owner_id="mallory",
            requirements={},
        )
