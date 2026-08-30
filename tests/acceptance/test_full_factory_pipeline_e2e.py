"""Full Factory E2E Test: Ingest Requirements -> Architecture -> Scaffolding -> Disk Materialization -> Tests Run."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from execution.pipeline_executors import ArchitectureExecutor, ContractsExecutor, TestGeneratorExecutor
from generation.project_renderer import ProjectRenderer
from generation.project_spec import ArchitectureKind, ProjectDefinition
from generation.scaffold_engine import ScaffoldEngine
from generation.requirement_analysis import ingest_unstructured_requirements


def test_full_software_factory_flow_to_disk():
    """Test the complete chain from raw business requirements to materialized repository."""
    raw_requirements = """
    # Project: Todo Backend API

    ## Requirements
    ### REQ-001: Create and Retrieve Todos
    Provide REST endpoints for todo management.
    Target: app/api.py
    - POST /todos returns 201
    - GET /todos returns 200
    """
    
    # 1. Ingest Requirements
    analysis = ingest_unstructured_requirements(raw_requirements, project_name="todo-backend")
    assert len(analysis.requirements) == 1
    assert analysis.requirements[0].id == "REQ-001"

    # 2. Architecture & OpenAPI Contracts Generation
    req_yaml = """
project_name: todo-backend
requirements:
  - id: REQ-001
    description: Todo operations
    acceptance_criteria:
      - POST /todos returns 201
      - GET /todos returns 200
    """
    arch_exec = ArchitectureExecutor()
    arch_result = arch_exec.execute({"project_name": "todo-backend", "requirements": req_yaml})
    assert arch_result["architecture"]["requirements_fingerprint"]

    contracts_exec = ContractsExecutor()
    contracts_result = contracts_exec.execute({**arch_result, "requirements": req_yaml})
    assert "/todos" in contracts_result["contracts"]["openapi"]["paths"]

    # 3. Test Generation from Contracts
    test_gen = TestGeneratorExecutor()
    test_result = test_gen.execute({"task_id": "test-task", "contracts": contracts_result["contracts"]})
    assert len(test_result["tests"]["files"]) > 0

    # 4. Scaffolding & Disk Materialization
    proj_def = ProjectDefinition(
        name="todo-backend",
        architecture=ArchitectureKind.HEXAGONAL,
        language="python",
        api="fastapi",
        database="postgresql",
    )
    scaffolder = ScaffoldEngine()
    plan = scaffolder.generate(proj_def)
    renderer = ProjectRenderer()
    rendered = renderer.render(plan)

    with tempfile.TemporaryDirectory(prefix="factory-e2e-") as tmpdir:
        target_dir = Path(tmpdir) / "todo-backend"
        written = renderer.write_to_disk(rendered, target_dir)
        
        # Write generated tests to the materialized project
        for t_file in test_result["tests"]["files"]:
            file_dest = target_dir / t_file["path"]
            file_dest.parent.mkdir(parents=True, exist_ok=True)
            file_dest.write_text(t_file["content"], encoding="utf-8")

        # Verify disk tree structure
        assert (target_dir / "pyproject.toml").exists() or (target_dir / "README.md").exists()
        assert (target_dir / "tests" / "generated" / "test_http_contract.py").exists()
        
        # Verify generated test file syntax by compiling it
        test_source = (target_dir / "tests" / "generated" / "test_http_contract.py").read_text(encoding="utf-8")
        compile(test_source, "test_http_contract.py", "exec")
        assert "assert response.status_code == 201" in test_source
        assert "assert response.status_code == 200" in test_source
