"""Tests for framework_independent enforcement and AST forbid_call."""
from pathlib import Path

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ConstraintV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from services.architecture_ast_call_matcher import find_forbidden_calls
from services.architecture_framework_independence import evaluate_framework_independence
from services.architecture_verification import verify_architecture


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_contract(*constraints: ConstraintV1) -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-fw",
        version="1.0.0",
        status="review",
        project_name="sample",
        style="hexagonal",
        layers=(
            LayerV1(id="domain", path="src/domain/**", framework_independent=True),
            LayerV1(id="application", path="src/application/**", framework_independent=True),
            LayerV1(id="adapters", path="src/adapters/**", framework_independent=False),
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


def test_framework_independent_blocks_fastapi_in_domain(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "api.py", "import fastapi\n")
    checks = evaluate_framework_independence(make_contract(), tmp_path)
    assert any(c.status == "FAIL" and "fastapi" in c.message for c in checks)


def test_framework_independent_allows_fastapi_in_adapters(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\n")
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    checks = evaluate_framework_independence(make_contract(), tmp_path)
    assert all(c.status == "PASS" for c in checks)


def test_forbid_call_detects_shell_true():
    source = "import subprocess\nsubprocess.call('ls', shell=True)\n"
    matches = find_forbidden_calls(
        source,
        path="src/adapters/run.py",
        callee="subprocess.call",
        keywords={"shell": True},
    )
    assert len(matches) == 1
    assert matches[0].line == 2


def test_forbid_call_constraint_in_verification(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    contract = make_contract(
        ConstraintV1(
            id="SEC-010",
            type="forbid_call",
            severity="block",
            scope=("src/**",),
            params={"callee": "subprocess.call", "keywords": {"shell": True}},
        )
    )
    result = verify_architecture(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "SEC-010" and c.status == "FAIL" for c in result.checks)


def test_forbid_call_passes_without_keyword(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call(['ls'])\n",
    )
    contract = make_contract(
        ConstraintV1(
            id="SEC-010",
            type="forbid_call",
            severity="block",
            scope=("src/**",),
            params={"callee": "subprocess.call", "keywords": {"shell": True}},
        )
    )
    result = verify_architecture(contract, tmp_path)
    assert result.status == "PASS"
