"""Acceptance test: full software-factory pipeline against the real runtime.

Runs the entire pipeline end-to-end against the canonical in-memory
orchestration (PipelineIntegration -> PipelineOrchestrator -> PipelineAdapter):

    start_pipeline -> requirements gate -> approve
        -> generate_architecture -> complete -> gate -> approve
        -> generate_contracts   -> complete -> gate -> approve
        -> generate_code        -> complete
        -> generate_tests       -> complete
        -> run_tests            -> complete
        -> deploy               -> complete
        -> release gate         -> approve
        -> released (terminal)

No external LLM/network required: the flow is driven by deterministic task
results, mirroring how the API layer completes executor work.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from runtime.core import DORRuntime
from runtime.pipeline_orchestrator import PipelineOrchestrator
from runtime.pipeline_integration import PipelineIntegration
from services.pipeline_adapter import PipelineAdapter


REQUIREMENTS_YAML = """
project_name: "Todo API"
project_description: "A simple Todo API with CRUD operations"
version: "1.0.0"

requirements:
  - id: REQ-001
    title: "Create todo"
    description: "User can create a new todo item"
    acceptance_criteria:
      - "POST /todos returns 201 with todo data"
      - "Validates required fields (title, description)"
      - "Returns 400 for invalid input"
      - "Returns 401 if not authenticated"
    priority: high
    security: "authentication_required: true"

  - id: REQ-002
    title: "List todos"
    description: "User can list all todo items"
    acceptance_criteria:
      - "GET /todos returns 200 with list of todos"
      - "Returns 401 if not authenticated"
    priority: high
    security: "authentication_required: true"

  - id: REQ-003
    title: "Get todo by ID"
    description: "User can get a specific todo by ID"
    acceptance_criteria:
      - "GET /todos/{id} returns 200 with todo data"
      - "Returns 404 if todo not found"
      - "Returns 401 if not authenticated"
    priority: high
    security: "authentication_required: true"
"""


def _build_runtime(tmp_path: Path) -> DORRuntime:
    """Fresh runtime with an isolated SQLite database per test run."""
    runtime = DORRuntime(database_url=f"sqlite:///{tmp_path / 'acceptance.db'}")
    runtime.boot()
    return runtime


def _synthesize_result(task) -> dict:
    """Produce a realistic result for the task type seen by the orchestrator."""
    task_type = (task.metadata or {}).get("task_type") or task.name
    if task_type == "generate_architecture":
        return {
            "architecture": {
                "name": "todo-api",
                "layers": ["api", "domain", "infra"],
                "decisions": ["Use FastAPI", "Use SQLite"],
            },
            "architecture_docs": [
                {
                    "path": "docs/architecture.md",
                    "content": "# Architecture\n\nTodo API hexagon.",
                }
            ],
        }
    if task_type == "generate_contracts":
        return {
            "contracts": {
                "openapi": "3.1.0",
                "paths": {
                    "/todos": {"post": {"responses": {"201": {}}}},
                    "/todos/{id}": {"get": {"responses": {"200": {}}}},
                },
            },
            "contract_docs": [
                {
                    "path": "docs/contracts.md",
                    "content": "# Contracts\n\nOpenAPI 3.1 contract for /todos.",
                }
            ],
        }
    if task_type == "generate_code":
        return {
            "files": [
                {
                    "path": "src/todo_api/main.py",
                    "content": (
                        "from fastapi import FastAPI\n\n"
                        "app = FastAPI()\n\n"
                        '@app.get("/health")\n'
                        "def health():\n"
                        '    return {"status": "ok"}\n'
                    ),
                },
                {
                    "path": "src/todo_api/todos.py",
                    "content": (
                        "from pydantic import BaseModel\n\n"
                        "class Todo(BaseModel):\n"
                        "    title: str\n"
                        "    description: str = ''\n"
                    ),
                },
            ]
        }
    if task_type == "generate_tests":
        return {
            "test_suites": [
                {
                    "path": "tests/test_todos.py",
                    "content": (
                        "def test_health():\n"
                        "    assert True  # placeholder\n"
                    ),
                }
            ],
            "test_files": [
                {
                    "path": "tests/test_todos.py",
                    "content": "def test_health():\n    assert True\n",
                }
            ],
        }
    if task_type == "run_tests":
        return {"tests_run": 12, "tests_passed": 12, "tests_failed": 0}
    if task_type == "deploy":
        return {
            "deployment": "staging",
            "url": "http://localhost:8000",
            "status": "deployed",
        }
    return {"status": "completed"}


def _complete_pending_task(orch: PipelineOrchestrator, workflow_id: str) -> None:
    tasks = orch.list_tasks(workflow_id)
    pending = [t for t in tasks if t.status.name == "PENDING"]
    assert pending, "expected a pending task to complete"
    task = pending[0]
    task.result = _synthesize_result(task)
    orch.handle_task_completion(task)


def _approve_pending_gate(orch: PipelineOrchestrator, workflow_id: str) -> None:
    wf = orch._workflows[workflow_id]
    for transition in getattr(wf, "transitions", []) or []:
        if getattr(transition, "from_state", None) != wf.current_state:
            continue
        gate_id = getattr(transition, "gate_id", None)
        if not gate_id:
            continue
        gate = next((g for g in wf.gates if g.id == gate_id), None)
        if gate is not None and not getattr(gate, "decision_id", None):
            assert orch.approve_gate(workflow_id, gate_id, "acceptance-approver")
            return
    for gate in wf.gates:
        if not getattr(gate, "decision_id", None):
            assert orch.approve_gate(workflow_id, gate.id, "acceptance-approver")
            return


def test_todo_api_pipeline_real_system(tmp_path: Path) -> None:
    runtime = _build_runtime(tmp_path)
    try:
        adapter = PipelineAdapter()
        orchestrator = PipelineOrchestrator(runtime, adapter)
        integration = PipelineIntegration(runtime, orchestrator=orchestrator)

        # --- Start ------------------------------------------------------
        workflow_id = integration.start_pipeline(
            REQUIREMENTS_YAML, "acceptance-org", "test-user"
        )
        assert workflow_id
        status = integration.status(workflow_id)
        assert status["state_name"] == "requirements_validated"
        print(f"\n🚀 Pipeline started: {workflow_id}")

        # --- Drive through the full flow -------------------------------
        terminal = {"released", "failed", "cancelled"}
        max_steps = 25
        step = 0
        while step < max_steps:
            step += 1
            status = integration.status(workflow_id)
            state = status["state_name"]
            print(f"   Step {step}: {state}")

            if state in terminal:
                break

            tasks = orchestrator.list_tasks(workflow_id)
            pending = [t for t in tasks if t.status.name == "PENDING"]
            if pending:
                _complete_pending_task(orchestrator, workflow_id)
                continue

            _approve_pending_gate(orchestrator, workflow_id)
            orchestrator.advance_pipeline(workflow_id)

        assert step < max_steps, "pipeline did not reach a terminal state"
        final = integration.status(workflow_id)
        assert final["state_name"] == "released"
        print(f"\n📊 Final state: {final['state_name']}")

        # --- Task / context sanity -------------------------------------
        tasks = orchestrator.list_tasks(workflow_id)
        task_types = {
            (t.metadata or {}).get("task_type") or t.name for t in tasks
        }
        print(f"   Tasks executed: {sorted(task_types)}")
        for expected in [
            "generate_architecture",
            "generate_contracts",
            "generate_code",
            "generate_tests",
            "run_tests",
            "deploy",
        ]:
            assert expected in task_types, f"missing task {expected} in flow"

        for t in tasks:
            assert t.status.name == "SUCCEEDED", f"task {t.id} not succeeded"

        # --- Artifact / YAML sanity ------------------------------------
        spec = yaml.safe_load(REQUIREMENTS_YAML)
        assert len(spec["requirements"]) == 3
        context = final["context"]
        files = (context.get("files") or []) if isinstance(context, dict) else []
        if files:
            for f in files:
                if f.get("path", "").endswith(".py"):
                    compile(f["content"], f["path"], "exec")

        print("\n🎉 Acceptance test passed!")
    finally:
        runtime.ready = False
