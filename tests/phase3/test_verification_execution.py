from __future__ import annotations

import sys

import pytest

from domain.distribution import DispatchRecord
from domain.verification import DeliveredProduct
from services.verification_execution import (
    CommandEvidenceAdapter,
    ExecutionBinding,
    VerificationExecutionError,
    bandit_adapter,
    compileall_adapter,
    provenance_adapter,
    pytest_adapter,
)
from services.verification_execution_service import VerificationExecutionService


PACKAGE = "package-fp"
CONTRACT = "contract-fp"
ARTIFACT = "artifact-fp"


def dispatch() -> DispatchRecord:
    return DispatchRecord(
        schema_version="0.1",
        dispatch_id="dispatch-1",
        task_id="task-1",
        task_fingerprint="task-fp",
        package_id="package-1",
        package_fingerprint=PACKAGE,
        selected_role="tester",
        contract_id="contract-1",
        contract_fingerprint=CONTRACT,
        required_inputs=("workspace",),
        permitted_outputs=("report.json",),
    )


def product() -> DeliveredProduct:
    return DeliveredProduct(
        artifact_id="artifact-1",
        artifact_fingerprint=ARTIFACT,
        output_names=("report.json",),
        evidence=(),
    )


def binding() -> ExecutionBinding:
    return ExecutionBinding(PACKAGE, CONTRACT, dispatch().fingerprint, ARTIFACT)


def test_command_adapter_produces_bound_pass_evidence(tmp_path):
    adapter = CommandEvidenceAdapter(
        "smoke",
        "test",
        (sys.executable, "-c", "raise SystemExit(0)"),
    )
    evidence = adapter.run(binding(), cwd=tmp_path)
    assert evidence.passed is True
    assert evidence.kind == "test"
    assert evidence.package_fingerprint == PACKAGE
    assert evidence.contract_fingerprint == CONTRACT
    assert evidence.dispatch_fingerprint == dispatch().fingerprint
    assert evidence.artifact_fingerprint == ARTIFACT


def test_command_adapter_records_failed_execution(tmp_path):
    adapter = CommandEvidenceAdapter(
        "smoke",
        "test",
        (sys.executable, "-c", "raise SystemExit(7)"),
    )
    evidence = adapter.run(binding(), cwd=tmp_path)
    assert evidence.passed is False
    assert "exit code 7" in evidence.statement


def test_adapter_rejects_invalid_workspace():
    adapter = CommandEvidenceAdapter("smoke", "test", (sys.executable, "-c", "pass"))
    with pytest.raises(VerificationExecutionError):
        adapter.run(binding(), cwd="/path/that/does/not/exist")


def test_execution_identity_is_deterministic():
    first = CommandEvidenceAdapter("smoke", "test", (sys.executable, "-c", "pass"))
    second = CommandEvidenceAdapter("smoke", "test", (sys.executable, "-c", "pass"))
    assert first.execution_id == second.execution_id


def test_canonical_adapters_have_expected_contracts():
    assert pytest_adapter().kind == "test"
    assert compileall_adapter().kind == "architecture"
    assert bandit_adapter().kind == "security"
    assert provenance_adapter().kind == "provenance"


def test_execution_service_produces_verifiable_product(tmp_path):
    adapters = (
        CommandEvidenceAdapter("tests", "test", (sys.executable, "-c", "pass")),
        CommandEvidenceAdapter("audit", "audit", (sys.executable, "-c", "pass")),
        CommandEvidenceAdapter("security", "security", (sys.executable, "-c", "pass")),
        CommandEvidenceAdapter("provenance", "provenance", (sys.executable, "-c", "pass")),
    )
    delivered, result = VerificationExecutionService().execute(
        dispatch(), product(), cwd=tmp_path, adapters=adapters
    )
    assert len(delivered.evidence) == 4
    assert result.status == "PASS"
    assert result.failures == ()
