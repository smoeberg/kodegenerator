"""Tests for explicit Project + plan persistence on pipeline workflows."""
from __future__ import annotations

import pytest

from services.pipeline_adapter import PipelineAdapter

_VALID_YAML = """\
version: '1.0'
project_name: Example
project_description: Example project
requirements:
  - id: REQ-001
    description: Deliver the requested change
    acceptance_criteria:
      - The behavior is observable
"""


def test_pipeline_adapter_persists_exact_case_scope_in_context_and_metadata() -> None:
    adapter = PipelineAdapter()
    workflow = adapter.create_pipeline_from_yaml(
        _VALID_YAML,
        "org-a",
        "alice",
        project_id="project-a",
        plan_request_fingerprint="a" * 64,
    )

    assert workflow.context["project_id"] == "project-a"
    assert workflow.context["plan_request_fingerprint"] == "a" * 64
    assert workflow.metadata["project_id"] == "project-a"
    assert workflow.metadata["plan_request_fingerprint"] == "a" * 64


def test_pipeline_adapter_rejects_half_bound_or_invalid_case_scope() -> None:
    adapter = PipelineAdapter()

    with pytest.raises(ValueError, match="supplied together"):
        adapter.create_pipeline_from_yaml(
            _VALID_YAML,
            "org-a",
            "alice",
            project_id="project-a",
        )

    with pytest.raises(ValueError, match="lowercase SHA-256"):
        adapter.create_pipeline_from_yaml(
            _VALID_YAML,
            "org-a",
            "alice",
            project_id="project-a",
            plan_request_fingerprint="NOT-A-FINGERPRINT",
        )


def test_legacy_pipeline_without_case_scope_remains_supported() -> None:
    adapter = PipelineAdapter()
    workflow = adapter.create_pipeline_from_yaml(_VALID_YAML, "org-a", "alice")

    assert "project_id" not in workflow.context
    assert "plan_request_fingerprint" not in workflow.context
