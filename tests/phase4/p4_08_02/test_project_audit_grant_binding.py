"""Regression tests for the canonical AI-3/AI-4 project-audit request binding."""

from __future__ import annotations

from phase4.project_audit.baseline import DORBaselineProjectAuditProvider
from phase4.project_audit.runtime import ProjectAuditRuntime

from tests.phase4.test_project_audit_runtime import _dor_files, _init_repository


def test_project_audit_authorizes_and_executes_one_canonical_request(tmp_path):
    _init_repository(tmp_path, _dor_files())

    run = ProjectAuditRuntime(tmp_path).run(
        repository="repository:smoeberg/kodegenerator",
        provider=DORBaselineProjectAuditProvider(),
    )

    request = run.report.request
    expected_request_id = request.request_fingerprint
    expected_parameters = tuple(sorted(request.execution_parameters().items()))

    assert run.authority.allowed
    assert run.authority.request_id == expected_request_id
    assert run.authority.parameters == expected_parameters
    assert run.execution.request_id == expected_request_id
    assert run.execution.status.value == "succeeded"
