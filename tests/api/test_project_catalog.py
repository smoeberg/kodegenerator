from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

from api.auth import User
from api.endpoints.control_plane import list_projects, router
from domain.project import Project, ProjectIntent, ProjectStatus


class _ScalarRows:
    def __init__(self, values: list[str]) -> None:
        self._values = values

    def all(self) -> list[str]:
        return list(self._values)


class _Session:
    def __init__(self, project_ids: list[str]) -> None:
        self.project_ids = project_ids
        self.statements = []

    def scalars(self, statement):
        self.statements.append(statement)
        return _ScalarRows(self.project_ids)


class _Database:
    def __init__(self, project_ids: list[str]) -> None:
        self.session_value = _Session(project_ids)
        self.organizations: list[str] = []

    @contextmanager
    def session(self, organization_id: str):
        self.organizations.append(organization_id)
        yield self.session_value


class _Projects:
    def __init__(self, projects: dict[str, Project]) -> None:
        self.projects = projects
        self.calls: list[tuple[object, str]] = []

    def get_project(self, context, project_id: str) -> Project:
        self.calls.append((context, project_id))
        return self.projects[project_id]


def _project(project_id: str, *, updated_hour: int) -> Project:
    timestamp = datetime(2026, 9, 5, updated_hour, tzinfo=timezone.utc)
    return Project(
        id=project_id,
        organization_id="org-1",
        name=f"Project {project_id}",
        description="",
        intent=ProjectIntent(goal=f"Build {project_id}"),
        status=ProjectStatus.CREATED,
        created_by="alice",
        created_at=timestamp,
        updated_at=timestamp,
    )


def test_control_plane_router_exposes_get_and_post_project_collection() -> None:
    methods = {
        method
        for route in router.routes
        if route.path == "/api/v1/control-plane/projects"
        for method in (getattr(route, "methods", ()) or ())
    }
    assert {"GET", "POST"} <= methods


def test_project_catalog_fails_closed_without_authenticated_organization() -> None:
    result = list_projects(
        current_user=User(username="alice", organization_id=None),
        dor=SimpleNamespace(),
    )

    assert result == {"organization_id": None, "projects": []}


def test_project_catalog_uses_tenant_query_and_canonical_project_read_boundary() -> None:
    project_2 = _project("project-2", updated_hour=12)
    project_1 = _project("project-1", updated_hour=11)
    database = _Database(["project-2", "project-1"])
    projects = _Projects({"project-1": project_1, "project-2": project_2})
    established_context = object()

    class FakeDOR:
        def __init__(self) -> None:
            self.database = database
            self.projects = projects

        def establish_context(self, *, principal, organization_id, actor_id):
            assert principal.id == "alice"
            assert organization_id == "org-1"
            assert actor_id == "alice"
            return established_context

    result = list_projects(
        current_user=User(username="alice", organization_id="org-1"),
        dor=FakeDOR(),
    )

    assert result["organization_id"] == "org-1"
    assert [project.project_id for project in result["projects"]] == [
        "project-2",
        "project-1",
    ]
    assert database.organizations == ["org-1"]
    assert [project_id for _, project_id in projects.calls] == [
        "project-2",
        "project-1",
    ]
    assert all(context is established_context for context, _ in projects.calls)
