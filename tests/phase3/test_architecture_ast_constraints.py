"""Tests for AST/source architecture constraint evaluation."""
from pathlib import Path

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ConstraintV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from services.architecture_ast_constraint_evaluator import evaluate_constraints
from services.architecture_verification import verify_architecture


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def base_contract(*constraints: ConstraintV1) -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-ast",
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
        constraints=constraints,
    )


def test_forbid_pattern_detects_shell_true(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="SEC-001",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "SEC-001" and c.status == "FAIL" for c in result.checks)


def test_forbid_pattern_passes_when_absent(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="SEC-001",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"


def test_require_pattern_fails_when_missing(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-010",
            type="require_pattern",
            pattern=r"class\s+Order\b",
            severity="block",
            scope=("src/domain/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"


def test_require_pattern_passes_when_present(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "class Order:\n    pass\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-010",
            type="require_pattern",
            pattern=r"class\s+Order\b",
            severity="block",
            scope=("src/domain/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"


def test_no_path_traversal_writes_detects_open(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def save(name):\n    open('../etc/passwd', 'w').write(name)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-001",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "CON-001" and c.status == "FAIL" for c in result.checks)


def test_unified_verification_combines_dependency_and_constraints(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        tmp_path / "src" / "application" / "service.py",
        "from src.domain import model\n",
    )
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="SEC-001",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=("src/**",),
        )
    )
    result = verify_architecture(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.type == "dependency_rule" for c in result.checks)
    assert any(c.rule_id == "SEC-001" for c in result.checks)


def test_unsupported_block_constraint_fails_closed(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-999",
            type="custom",
            severity="block",
            description="not implemented yet",
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("Unsupported constraint type" in c.message for c in result.checks)
