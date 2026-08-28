"""Requirement-driven architecture, contract, and test generation tests."""

from __future__ import annotations

from execution.pipeline_executors import ArchitectureExecutor, ContractsExecutor
from execution.pipeline_executors import (
    TestGeneratorExecutor as PipelineTestGenerator,
)

REQUIREMENTS = """
project_name: Todo API
requirements:
  - id: REQ-001
    description: Todo operations
    acceptance_criteria:
      - POST /todos returns 201
      - GET /todos returns 200
"""


def test_requirements_flow_into_architecture_and_contracts() -> None:
    architecture = ArchitectureExecutor().execute(
        {"project_name": "todo-api", "requirements": REQUIREMENTS}
    )
    assert architecture["architecture"]["requirements_fingerprint"]
    assert len(architecture["architecture"]["criteria"]) == 2

    contracts = ContractsExecutor().execute(
        {**architecture, "requirements": REQUIREMENTS}
    )
    generated = contracts["contracts"]
    assert generated["openapi"]["paths"]["/todos"]["post"]["responses"]["201"]
    assert generated["openapi"]["paths"]["/todos"]["get"]["responses"]["200"]
    assert len(generated["traceability"]) == 2


def test_contract_tests_cover_every_explicit_http_criterion() -> None:
    architecture = ArchitectureExecutor().execute(
        {"project_name": "todo-api", "requirements": REQUIREMENTS}
    )
    contracts = ContractsExecutor().execute(
        {**architecture, "requirements": REQUIREMENTS}
    )
    result = PipelineTestGenerator().execute(
        {"task_id": "task-tests", "contracts": contracts["contracts"]}
    )
    tests = result["tests"]
    assert len(tests["covered_criteria"]) == 2
    source = tests["files"][0]["content"]
    compile(source, tests["files"][0]["path"], "exec")
    assert "assert response.status_code == 201" in source
    assert "assert response.status_code == 200" in source
    assert "assert True" not in source


def test_contract_generation_rejects_unmapped_requirements() -> None:
    requirements = """
requirements:
  - id: REQ-001
    acceptance_criteria: [Users can do something unspecified]
"""
    architecture = ArchitectureExecutor().execute(
        {"project_name": "demo", "requirements": requirements}
    )
    try:
        ContractsExecutor().execute({**architecture, "requirements": requirements})
    except ValueError as exc:
        assert "no explicit HTTP expectations" in str(exc)
    else:
        raise AssertionError("expected fail-closed contract generation")
