"""Tests for AST import extraction and architecture dependency evidence adapter."""
from pathlib import Path

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from domain.verification import Evidence
from services.architecture_dependency_adapter import architecture_dependency_adapter
from services.python_import_graph import collect_import_edges
from services.verification_execution import ExecutionBinding


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_contract() -> ArchitectureContractV1:
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


def test_collect_import_edges_resolves_internal_imports(tmp_path: Path):
    root = tmp_path
    _write(root / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        root / "src" / "application" / "service.py",
        "from src.domain.model import VALUE\n",
    )
    _write(
        root / "src" / "adapters" / "api.py",
        "from src.application import service\n",
    )
    # External import must be ignored.
    _write(root / "src" / "adapters" / "ext.py", "import json\n")

    edges = collect_import_edges(root)
    pairs = {(e.source_path, e.target_path) for e in edges}
    assert ("src/application/service.py", "src/domain/model.py") in pairs
    assert ("src/adapters/api.py", "src/application/service.py") in pairs
    assert not any(target.endswith("json.py") for _, target in pairs)


def test_adapter_passes_on_valid_layer_graph(tmp_path: Path):
    root = tmp_path
    _write(root / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        root / "src" / "application" / "service.py",
        "from src.domain import model\n",
    )

    contract = make_contract()
    adapter = architecture_dependency_adapter(contract)
    binding = ExecutionBinding(
        package_fingerprint="pkg" + "a" * 61,
        contract_fingerprint=contract.fingerprint,
        dispatch_fingerprint="dsp" + "b" * 61,
        artifact_fingerprint="art" + "c" * 61,
    )
    evidence = adapter.run(binding, cwd=root)
    assert isinstance(evidence, Evidence)
    assert evidence.kind == "architecture"
    assert evidence.passed is True
    assert evidence.contract_fingerprint == contract.fingerprint


def test_adapter_fails_on_forbidden_domain_to_adapters(tmp_path: Path):
    root = tmp_path
    _write(root / "src" / "adapters" / "db.py", "ENGINE = 'x'\n")
    _write(
        root / "src" / "domain" / "model.py",
        "from src.adapters import db\n",
    )

    contract = make_contract()
    adapter = architecture_dependency_adapter(contract)
    binding = ExecutionBinding(
        package_fingerprint="pkg" + "a" * 61,
        contract_fingerprint=contract.fingerprint,
        dispatch_fingerprint="dsp" + "b" * 61,
        artifact_fingerprint="art" + "c" * 61,
    )
    evidence = adapter.run(binding, cwd=root)
    assert evidence.passed is False
    assert "FAIL" in evidence.statement


def test_adapter_fails_on_contract_fingerprint_mismatch(tmp_path: Path):
    root = tmp_path
    _write(root / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = make_contract()
    adapter = architecture_dependency_adapter(contract)
    binding = ExecutionBinding(
        package_fingerprint="pkg" + "a" * 61,
        contract_fingerprint="0" * 64,
        dispatch_fingerprint="dsp" + "b" * 61,
        artifact_fingerprint="art" + "c" * 61,
    )
    evidence = adapter.run(binding, cwd=root)
    assert evidence.passed is False
    assert "fingerprint mismatch" in evidence.statement


def test_evaluate_workspace_exposes_structured_result(tmp_path: Path):
    root = tmp_path
    _write(root / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        root / "src" / "application" / "service.py",
        "from src.domain import model\n",
    )
    contract = make_contract()
    result = architecture_dependency_adapter(contract).evaluate_workspace(root)
    assert result.status == "PASS"
    assert result.contract_fingerprint == contract.fingerprint
    assert result.to_dict()["schema_version"] == "1.0"
