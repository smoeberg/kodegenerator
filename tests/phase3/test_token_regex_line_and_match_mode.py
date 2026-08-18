"""Tests for line numbers and match_mode in token-regex constraints."""
from pathlib import Path

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ConstraintV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from services.architecture_ast_constraint_evaluator import evaluate_constraints
from services.architecture_ast_source import line_number_at, prepare_pattern_source


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def base_contract(*constraints: ConstraintV1) -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-token",
        version="1.0.0",
        status="review",
        project_name="sample",
        style="hexagonal",
        layers=(
            LayerV1(id="domain", path="src/domain/**"),
            LayerV1(id="adapters", path="src/adapters/**"),
        ),
        dependency_rules=(
            DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=(), severity="block"),
            DependencyRuleV1(
                id="DEP-002",
                source="adapters",
                may_depend_on=("domain",),
                severity="block",
            ),
        ),
        quality_gates=(QualityGateV1(id="QG-dep", type="dependency_rules", required=True),),
        constraints=constraints,
    )


def test_prepare_pattern_source_preserves_offsets_for_line_numbers():
    source = "a = 1\n# bad pattern here\nb = 2\n"
    prepared = prepare_pattern_source(source, match_mode="include_strings")
    assert len(prepared) == len(source)
    assert "#" not in prepared
    assert line_number_at(source, prepared.index("b")) == 3


def test_forbid_pattern_reports_line_number(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import os\n\nx = 1\nsubprocess.call('ls', shell=True)\n",
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
    hit = next(c for c in result.checks if c.status == "FAIL")
    assert hit.source_line == 4
    assert "line 4" in hit.message
    assert hit.to_dict()["locations"][0]["line"] == 4


def test_code_only_ignores_docstring_example(tmp_path: Path):
    _write(
        tmp_path / "src" / "domain" / "model.py",
        '"""Example: subprocess.call(\'ls\', shell=True)\n"""\nVALUE = 1\n',
    )
    # include_strings should still fail
    contract_include = base_contract(
        ConstraintV1(
            id="SEC-001",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=("src/**",),
            params={"match_mode": "include_strings"},
        )
    )
    assert evaluate_constraints(contract_include, tmp_path).status == "FAIL"

    # code_only should pass (docstring blanked)
    contract_code = base_contract(
        ConstraintV1(
            id="SEC-001",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=("src/**",),
            params={"match_mode": "code_only"},
        )
    )
    assert evaluate_constraints(contract_code, tmp_path).status == "PASS"


def test_code_only_still_flags_real_code(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        '"""docs only"""\nimport subprocess\nsubprocess.call("ls", shell=True)\n',
    )
    contract = base_contract(
        ConstraintV1(
            id="SEC-001",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=("src/**",),
            params={"match_mode": "code_only"},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    hit = next(c for c in result.checks if c.status == "FAIL")
    assert hit.source_line == 3
