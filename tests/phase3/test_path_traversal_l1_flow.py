"""L1 local dataflow tests for no_path_traversal_writes."""
from pathlib import Path

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ConstraintV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from services.architecture_ast_constraint_evaluator import (
    _find_path_traversal_writes,
    evaluate_constraints,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def base_contract(*constraints: ConstraintV1) -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-l1-path",
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


def _constraint() -> ConstraintV1:
    return ConstraintV1(
        id="CON-TRAV",
        type="no_path_traversal_writes",
        severity="block",
        scope=("src/**",),
    )


def test_l1_detects_name_bound_to_traversal_literal():
    source = (
        "def save(data):\n"
        "    path = '../etc/passwd'\n"
        "    open(path, 'w').write(data)\n"
    )
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits
    assert hits[0][0] == 3


def test_l1_detects_module_level_name_flow():
    source = (
        "out = '../secret'\n"
        "open(out, 'w').write('x')\n"
    )
    hits = _find_path_traversal_writes(source, "mod.py")
    assert hits


def test_l1_ignores_name_reassigned_to_safe_literal():
    source = (
        "def save(data):\n"
        "    path = '../etc/passwd'\n"
        "    path = 'safe.txt'\n"
        "    open(path, 'w').write(data)\n"
    )
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits == []


def test_l1_ignores_unknown_name():
    source = (
        "def save(path, data):\n"
        "    open(path, 'w').write(data)\n"
    )
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits == []


def test_l1_ignores_non_literal_assignment():
    source = (
        "def save(base, data):\n"
        "    path = base + '/../x'\n"
        "    open(path, 'w').write(data)\n"
    )
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits == []


def test_l1_scopes_do_not_leak_across_functions():
    source = (
        "def other():\n"
        "    path = '../etc/passwd'\n"
        "\n"
        "def save(data):\n"
        "    open(path, 'w').write(data)\n"
    )
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits == []


def test_l1_still_detects_direct_literal():
    source = "open('../x', 'w').write('y')\n"
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits


def test_l1_annassign_literal_flow():
    source = (
        "def save(data):\n"
        "    path: str = '../evil'\n"
        "    open(path, mode='w').write(data)\n"
    )
    hits = _find_path_traversal_writes(source, "sample.py")
    assert hits


def test_l1_integrated_constraint_fails(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def save(name):\n"
        "    target = '../etc/passwd'\n"
        "    open(target, 'w').write(name)\n",
    )
    result = evaluate_constraints(base_contract(_constraint()), tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "CON-TRAV" and c.status == "FAIL" for c in result.checks)


def test_l1_integrated_safe_name_passes(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def save(name):\n"
        "    target = 'out.txt'\n"
        "    open(target, 'w').write(name)\n",
    )
    result = evaluate_constraints(base_contract(_constraint()), tmp_path)
    assert result.status == "PASS"
