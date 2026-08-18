from __future__ import annotations

import sys
from pathlib import Path

import pytest

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
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


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def architecture_contract() -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-sample",
        version="1.0.0",
        status="review",
        project_name="sample",
        style="hexagonal",
        layers=(
            LayerV1(id="domain", path="src/domain/**"),
            LayerV1(id="application", path="src/application/**"),
            LayerV1(id="adapters", path="src/adapters/**"),
        ),
        dependency_rules=(
            DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=(), severity="block"),
            DependencyRuleV1(
                id="DEP-002",
                source="application",
                may_depend_on=("domain",),
                severity="block",
            ),
            DependencyRuleV1(
                id="DEP-003",
                source="adapters",
                may_depend_on=("domain", "application"),
                severity="block",
            ),
        ),
        quality_gates=(QualityGateV1(id="QG-dep", type="dependency_rules", required=True),),
    )


def core_adapters():
    return (
        CommandEvidenceAdapter("tests", "test", (sys.executable, "-c", "pass")),
        CommandEvidenceAdapter("audit", "audit", (sys.executable, "-c", "pass")),
        CommandEvidenceAdapter("security", "security", (sys.executable, "-c", "pass")),
        CommandEvidenceAdapter("provenance", "provenance", (sys.executable, "-c", "pass")),
    )


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
    root = tmp_path
    _write(root / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        root / "src" / "application" / "service.py",
        "from src.domain import model\n",
    )
    delivered, result = VerificationExecutionService().execute(
        dispatch(),
        product(),
        cwd=root,
        adapters=core_adapters(),
        architecture_contract=architecture_contract(),
    )
    assert len(delivered.evidence) == 5
    assert result.status == "PASS"
    assert result.failures == ()


def test_execution_service_requires_adapters_or_architecture_contract(tmp_path):
    with pytest.raises(VerificationExecutionError, match="architecture_contract"):
        VerificationExecutionService().execute(
            dispatch(), product(), cwd=tmp_path, adapters=()
        )


def test_execution_service_runs_architecture_contract_adapter(tmp_path):
    root = tmp_path
    _write(root / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        root / "src" / "application" / "service.py",
        "from src.domain import model\n",
    )
    delivered, result = VerificationExecutionService().execute(
        dispatch(),
        product(),
        cwd=root,
        adapters=core_adapters(),
        architecture_contract=architecture_contract(),
    )
    assert len(delivered.evidence) == 5
    architecture = next(item for item in delivered.evidence if item.kind == "architecture")
    assert architecture.passed is True
    assert architecture.contract_fingerprint == CONTRACT
    assert result.status == "PASS"


def test_execution_service_architecture_violation_fails_gate(tmp_path):
    """Architecture FAIL is required evidence and blocks overall P3-20 PASS."""
    root = tmp_path
    _write(root / "src" / "adapters" / "db.py", "ENGINE = 'x'\n")
    _write(
        root / "src" / "domain" / "model.py",
        "from src.adapters import db\n",
    )
    delivered, result = VerificationExecutionService().execute(
        dispatch(),
        product(),
        cwd=root,
        adapters=core_adapters(),
        architecture_contract=architecture_contract(),
    )
    architecture = next(item for item in delivered.evidence if item.kind == "architecture")
    assert architecture.passed is False
    assert result.status == "FAIL"
    assert any("Required architecture evidence" in failure for failure in result.failures)
