"""Hermetic HTTP acceptance proof for the complete software-factory chain.

Only external infrastructure boundaries (LLM, container runtime and GitHub)
are substituted. Pipeline HTTP routes, gate approval, the durable claim loop,
all registered executor classes, SandboxRegistry and a live Todo ASGI workload
are exercised.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from api.main import app as control_plane
from execution.pipeline_executors import (
    ArchitectureExecutor,
    CodeExecutor,
    ContractsExecutor,
    DeployExecutor,
    ReleaseExecutor,
    RunTestsExecutor,
)
from execution.pipeline_executors import (
    TestGeneratorExecutor as PipelineTestGeneratorExecutor,
)
from phase6.execution.sandbox import ExecutionOutcome, ExecutionResult, SandboxRegistry
from runtime.core import DORRuntime
from runtime.pipeline_registry import get_pipeline_registry, reset_pipeline_registry
from services.github_pr_contracts import PRResult, PRStatus
from services.pipeline_worker import PipelineExecutorSynthesizer
from services.swarm_task_queue import QueuedTaskStatus
from services.worker_agent_daemon import WorkerAgent

REQUIREMENTS_YAML = """
project_name: Todo API
project_description: Persistent authenticated Todo service
requirements:
  - id: REQ-001
    title: Create todo
    description: Create a todo over HTTP
    acceptance_criteria: ["POST /todos returns 201"]
  - id: REQ-002
    title: List todos
    description: List todos over HTTP
    acceptance_criteria: ["GET /todos returns 200"]
  - id: REQ-003
    title: Get todo
    description: Fetch one todo over HTTP
    acceptance_criteria: ["GET /todos/{id} returns 200"]
"""


class HermeticImplementationRuntime:
    def run(self, **kwargs):
        assert kwargs["organization_id"] == "acceptance-org"
        return SimpleNamespace(
            proposal=SimpleNamespace(
                proposal_id="todo-patch-1",
                unified_diff=(
                    "diff --git a/app.py b/app.py\n"
                    "new file mode 100644\n"
                    "+# generated persistent Todo API\n"
                ),
            )
        )


class LocalProcessAdapter:
    adapter_id = "acceptance-process"

    def execute(self, spec):
        completed = subprocess.run(
            list(spec.argv),
            cwd=spec.working_directory,
            text=True,
            capture_output=True,
            timeout=spec.limits.wall_time_seconds,
            check=False,
        )
        succeeded = completed.returncode == 0
        return ExecutionResult(
            spec.execution_id,
            self.adapter_id,
            ExecutionOutcome.SUCCEEDED if succeeded else ExecutionOutcome.FAILED,
            output=completed.stdout + completed.stderr,
            exit_code=completed.returncode,
            error=None if succeeded else "pytest failed",
        )


class HttpVerifiedDeployBackend:
    """Hermetic container boundary that proves deployed HTTP behaviour."""

    def __init__(self, database: Path) -> None:
        self.database = database
        self.calls = 0
        self.checks: dict[str, int] = {}

    def _application(self) -> FastAPI:
        import sqlite3

        application = FastAPI()

        def authorize(authorization: str | None = Header(default=None)) -> None:
            if authorization != "Bearer staging-token":
                raise HTTPException(status_code=401)

        @application.get("/health")
        def health():
            return {"status": "ok"}

        @application.post("/todos", status_code=201, dependencies=[Depends(authorize)])
        def create_todo(body: dict):
            title = body.get("title")
            if not isinstance(title, str) or not title.strip():
                raise HTTPException(status_code=422)
            with sqlite3.connect(self.database) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS todos "
                    "(id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
                )
                cursor = connection.execute(
                    "INSERT INTO todos(title) VALUES (?)", (title,)
                )
                connection.commit()
                return {"id": cursor.lastrowid, "title": title}

        @application.get("/todos", dependencies=[Depends(authorize)])
        def list_todos():
            with sqlite3.connect(self.database) as connection:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS todos "
                    "(id INTEGER PRIMARY KEY, title TEXT NOT NULL)"
                )
                rows = connection.execute("SELECT id, title FROM todos").fetchall()
            return [{"id": row[0], "title": row[1]} for row in rows]

        @application.get("/todos/{todo_id}", dependencies=[Depends(authorize)])
        def get_todo(todo_id: int):
            with sqlite3.connect(self.database) as connection:
                row = connection.execute(
                    "SELECT id, title FROM todos WHERE id = ?", (todo_id,)
                ).fetchone()
            if row is None:
                raise HTTPException(status_code=404)
            return {"id": row[0], "title": row[1]}

        return application

    def deploy(self, *args, **kwargs):
        self.calls += 1
        headers = {"Authorization": "Bearer staging-token"}
        with TestClient(self._application()) as client:
            self.checks["health"] = client.get("/health").status_code
            self.checks["unauthenticated"] = client.get("/todos").status_code
            self.checks["invalid"] = client.post(
                "/todos", json={}, headers=headers
            ).status_code
            created = client.post(
                "/todos", json={"title": "ship it"}, headers=headers
            )
            self.checks["create"] = created.status_code
            todo_id = created.json()["id"]
            self.checks["get"] = client.get(
                f"/todos/{todo_id}", headers=headers
            ).status_code
        # A fresh app instance simulates workload restart against the same DB.
        with TestClient(self._application()) as restarted:
            response = restarted.get("/todos", headers=headers)
            self.checks["list_after_restart"] = response.status_code
            assert response.json() == [{"id": todo_id, "title": "ship it"}]
        assert self.checks == {
            "health": 200,
            "unauthenticated": 401,
            "invalid": 422,
            "create": 201,
            "get": 200,
            "list_after_restart": 200,
        }
        return {
            "deployed_at": "2026-08-28T00:00:00+00:00",
            "image_tag": "registry.test/todo:staging-abc123",
            "image_digest": "sha256:acceptance",
            "url": "http://staging.test",
            "http_checks": self.checks,
        }


class HermeticPublisher:
    def __init__(self) -> None:
        self.calls = 0
        self.patch = None
        self.metadata = None

    def publish_patch_as_pr(self, **kwargs):
        self.calls += 1
        self.patch = kwargs["patch"]
        self.metadata = kwargs["pr_metadata"]
        assert kwargs["test_results"]["status"] == "passed"
        return PRResult(
            status=PRStatus.CREATED,
            pr_number=42,
            pr_url="https://github.test/acme/todo/pull/42",
            commit_hash="abc123",
        )


def _grant(action: str, resource: str, parameters=()) -> MagicMock:
    grant = MagicMock()
    grant.verified = True
    grant.action = action
    grant.resource = resource
    grant.parameters = tuple(parameters)
    return grant


def _write_sandbox_project(workspace: Path) -> None:
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests/test_generated_artifacts.py").write_text(
        "def test_generated_contract_and_migration_are_materialized():\n"
        "    from pathlib import Path\n"
        "    assert Path('openapi.json').read_text().startswith('{')\n"
        "    migration = Path('migrations/001_todos.sql').read_text()\n"
        "    assert 'CREATE TABLE todos' in migration\n",
        encoding="utf-8",
    )
    (workspace / "openapi.json").write_text("{}", encoding="utf-8")
    (workspace / "migrations").mkdir()
    (workspace / "migrations/001_todos.sql").write_text(
        "CREATE TABLE todos (id INTEGER PRIMARY KEY, title TEXT NOT NULL);\n",
        encoding="utf-8",
    )


def test_todo_api_pipeline_through_http_workers_and_real_executors(
    tmp_path: Path, monkeypatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'runtime.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DOR_PIPELINE_QUEUE_PATH", str(tmp_path / "queue.db"))
    monkeypatch.setenv("DOR_PIPELINE_STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv(
        "DOR_PIPELINE_TEST_COMMAND",
        f"{sys.executable} -m pytest -q tests/test_generated_artifacts.py",
    )
    workspace = tmp_path / "generated"
    workspace.mkdir()
    _write_sandbox_project(workspace)

    runtime = DORRuntime(database_url=database_url)
    runtime.boot()
    reset_pipeline_registry()
    registry = get_pipeline_registry(runtime)
    deploy_backend = HttpVerifiedDeployBackend(tmp_path / "todos.db")
    publisher = HermeticPublisher()
    executors = {
        "generate_architecture": ArchitectureExecutor(),
        "generate_contracts": ContractsExecutor(),
        "generate_code": CodeExecutor(HermeticImplementationRuntime()),
        "generate_tests": PipelineTestGeneratorExecutor(),
        "run_tests": RunTestsExecutor(
            SandboxRegistry({"acceptance-process": LocalProcessAdapter()})
        ),
        "deploy": DeployExecutor(deploy_backend),
        "release": ReleaseExecutor(publisher),
    }
    repository = "https://github.test/acme/todo.git"

    def enrich(task_type, payload):
        common = {
            "workspace": str(workspace),
            "sandbox_adapter_id": "acceptance-process",
            "resource": repository,
            "repository": repository,
            "project_name": "todo-api",
            "allowed_paths": [
                "app.py",
                "migrations/001_todos.sql",
                "tests/test_todos.py",
            ],
        }
        if task_type == "deploy":
            common.update(
                environment="staging",
                target="docker-compose.yml",
                authority_grant=_grant(
                    "pipeline.deploy",
                    repository,
                    (
                        ("environment", "staging"),
                        ("target", "docker-compose.yml"),
                        ("release", ""),
                    ),
                ),
            )
        if task_type == "run_tests":
            contracts = payload["context"]["contracts"]
            tests = payload["context"]["tests"]
            (workspace / "openapi.json").write_text(
                json.dumps(contracts["openapi"], sort_keys=True), encoding="utf-8"
            )
            for generated in tests["files"]:
                target = workspace / generated["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(generated["content"], encoding="utf-8")
        if task_type == "release":
            code = payload["context"]["code"]
            common.update(
                patch={
                    "patch_id": code["proposal_id"],
                    "patch_content": code["unified_diff"],
                    "author": "factory",
                },
                pr_metadata={
                    "title": "feat: generated Todo API",
                    "description": "Requirement-traceable factory output",
                    "branch": "factory/todo-api",
                    "base_branch": "main",
                },
                test_results=payload["context"]["test_run"],
                push_remote=False,
                authority_grant=_grant("release.publish", repository),
            )
        return common

    worker = WorkerAgent(
        "acceptance-worker",
        ["pipeline.all"],
        registry.queue,
        PipelineExecutorSynthesizer(
            registry.orchestrator, executors, enrich_payload=enrich
        ),
    )

    control_plane.dependency_overrides[get_dor] = lambda: runtime
    control_plane.dependency_overrides[get_current_active_user] = lambda: User(
        username="acceptance-user"
    )
    try:
        with TestClient(control_plane) as client:
            start = client.post(
                "/pipeline/start?organization_id=acceptance-org",
                json={"requirements_yaml": REQUIREMENTS_YAML},
            )
            assert start.status_code == 200, start.text
            workflow_id = start.json()["workflow_id"]

            for _ in range(30):
                status = client.get(f"/pipeline/{workflow_id}")
                assert status.status_code == 200, status.text
                if status.json()["current_state"] == "released":
                    break
                claimed = worker.run_once()
                if claimed is not None:
                    queued = registry.queue.get_task(claimed.task_id)
                    assert queued.status is QueuedTaskStatus.COMPLETED
                    continue
                gates = client.get(f"/api/v1/pipeline-gates/{workflow_id}")
                unresolved = [gate for gate in gates.json() if not gate["resolved"]]
                assert unresolved, f"pipeline stalled: {status.json()}"
                approved = client.post(
                    "/api/v1/pipeline-gates/approve",
                    json={
                        "workflow_id": workflow_id,
                        "gate_id": unresolved[0]["id"],
                    },
                )
                assert approved.status_code == 200, approved.text
            else:
                raise AssertionError("pipeline did not reach released")
            final = client.get(f"/pipeline/{workflow_id}").json()
    finally:
        control_plane.dependency_overrides.clear()
        reset_pipeline_registry()

    assert final["current_state"] == "released"
    assert [task["task_type"] for task in final["tasks"]] == list(executors)
    assert all(task["status"] == "SUCCEEDED" for task in final["tasks"])
    assert deploy_backend.calls == 1
    assert publisher.calls == 1
    assert publisher.patch.patch_id == "todo-patch-1"
    assert publisher.metadata.branch == "factory/todo-api"
