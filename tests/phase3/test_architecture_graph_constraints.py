"""Tests for max_module_fanout and allowlisted_dependencies_only."""
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
        contract_id="arch-graph",
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


def test_max_module_fanout_fails_when_exceeded(tmp_path: Path):
    # Create several target modules
    for name in ("a", "b", "c"):
        _write(tmp_path / "src" / "domain" / f"{name}.py", f"VALUE_{name.upper()} = 1\n")
    # Hub imports three modules → fanout 3
    _write(
        tmp_path / "src" / "application" / "hub.py",
        "from src.domain import a\nfrom src.domain import b\nfrom src.domain import c\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN",
            type="max_module_fanout",
            severity="block",
            scope=("src/application/**",),
            params={"max_fanout": 2},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("fanout" in c.message.lower() for c in result.checks if c.status == "FAIL")


def test_max_module_fanout_passes_within_limit(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    _write(tmp_path / "src" / "application" / "svc.py", "from src.domain import a\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={"max_fanout": 5},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"


def test_allowlisted_dependencies_blocks_unknown(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\nimport httpx\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW",
            type="allowlisted_dependencies_only",
            severity="block",
            scope=("src/**",),
            params={"allowlist": ["fastapi"]},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("httpx" in c.message for c in result.checks if c.status == "FAIL")


def test_allowlisted_dependencies_passes_when_allowed(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\n")
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW",
            type="allowlisted_dependencies_only",
            severity="block",
            scope=("src/**",),
            params={"allowlist": ["fastapi"]},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"


def test_graph_constraints_in_unified_verification(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW",
            type="allowlisted_dependencies_only",
            severity="block",
            scope=("src/**",),
            params={"allowlist": ["fastapi"]},
        ),
        ConstraintV1(
            id="CON-FAN",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={"max_fanout": 10},
        ),
    )
    result = verify_architecture(contract, tmp_path)
    assert result.status == "PASS"
