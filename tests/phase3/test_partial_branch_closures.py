# AUTO-MERGED union of main + PR76 versions
"""Close partial branch gaps in architecture constraint evaluators.

Targets branches that line coverage can hide:
- severity=warn / info paths in _status_for_severity
- unsupported constraint types with non-block severity (SKIPPED)
- invalid max_fanout / allowlist config (fail-closed)
- empty constraint scope (all paths in scope)
- path-traversal: read-only open; open mode keyword; write_text args
- exception policy: WARN suppression and target_path fallback
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ConstraintV1,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from domain.architecture_exceptions import ExceptionV1
from services.architecture_ast_constraint_evaluator import evaluate_constraints
from services.architecture_dependency_evaluator import CheckResult
from services.architecture_exception_policy import apply_exceptions, overall_status



def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def base_contract(*constraints: ConstraintV1) -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-partial-branch",
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


def test_max_module_fanout_warn_does_not_fail_overall(tmp_path: Path):
    for name in ("a", "b", "c"):
        _write(tmp_path / "src" / "domain" / f"{name}.py", f"VALUE_{name.upper()} = 1\n")
    _write(
        tmp_path / "src" / "application" / "hub.py",
        "from src.domain import a\nfrom src.domain import b\nfrom src.domain import c\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-WARN",
            type="max_module_fanout",
            severity="warn",
            scope=("src/application/**",),
            params={"max_fanout": 2},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(c.status == "WARN" for c in result.checks)
    assert any("fanout" in c.message.lower() for c in result.checks if c.status == "WARN")


def test_allowlisted_dependencies_warn_status(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\nimport httpx\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW-WARN",
            type="allowlisted_dependencies_only",
            severity="warn",
            scope=("src/**",),
            params={"allowlist": ["fastapi"]},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(c.status == "WARN" and "httpx" in c.message for c in result.checks)


def test_forbid_pattern_info_severity_treats_violation_as_pass(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="SEC-INFO",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="info",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(
        c.rule_id == "SEC-INFO" and c.status == "PASS" and "Forbidden pattern matched" in c.message
        for c in result.checks
    )


def test_unsupported_warn_constraint_is_skipped(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-CUSTOM",
            type="custom",
            severity="warn",
            description="not implemented",
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(
        c.rule_id == "CON-CUSTOM" and c.status == "SKIPPED" and "Unsupported" in c.message
        for c in result.checks
    )


def test_unsupported_info_constraint_is_skipped(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "model.py", "VALUE = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-CUSTOM-INFO",
            type="custom",
            severity="info",
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(c.rule_id == "CON-CUSTOM-INFO" and c.status == "SKIPPED" for c in result.checks)


def test_max_module_fanout_missing_param_fails_config(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-CFG",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(
        c.status == "FAIL" and "max_fanout" in c.message and "non-negative integer" in c.message
        for c in result.checks
    )


def test_max_module_fanout_negative_fails_config(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-NEG",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={"max_fanout": -1},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("non-negative integer" in c.message for c in result.checks if c.status == "FAIL")


def test_max_module_fanout_non_int_fails_config(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-STR",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={"max_fanout": "two"},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("non-negative integer" in c.message for c in result.checks if c.status == "FAIL")


def test_allowlist_not_a_list_fails_config(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW-CFG",
            type="allowlisted_dependencies_only",
            severity="block",
            scope=("src/**",),
            params={"allowlist": "fastapi"},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(
        c.status == "FAIL" and "allowlist" in c.message.lower() and "list" in c.message.lower()
        for c in result.checks
    )


def test_empty_scope_includes_all_paths_for_forbid_pattern(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="SEC-EMPTY-SCOPE",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="block",
            scope=(),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "SEC-EMPTY-SCOPE" and c.status == "FAIL" for c in result.checks)


def test_empty_scope_fanout_still_evaluates(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    _write(tmp_path / "src" / "application" / "svc.py", "from src.domain import a\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-EMPTY",
            type="max_module_fanout",
            severity="block",
            scope=(),
            params={"max_fanout": 10},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"


def test_read_only_open_with_traversal_does_not_fail(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def load():\n    return open('../etc/passwd', 'r').read()\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-TRAVERSE",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert all(c.status != "FAIL" for c in result.checks if c.rule_id == "CON-TRAVERSE")


def test_open_write_mode_keyword_with_traversal_fails(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def save(name):\n    open('../etc/passwd', mode='w').write(name)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-OPEN-KW",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "CON-OPEN-KW" and c.status == "FAIL" for c in result.checks)


def test_open_binary_write_with_traversal_fails(tmp_path: Path):
    """Exercise open mode containing 'w' via binary write ('wb')."""
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def save(data):\n    open('../out.bin', 'wb').write(data)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-WB",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "CON-WB" and c.status == "FAIL" for c in result.checks)


def test_write_text_arg_with_traversal_fails(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "from pathlib import Path\n\ndef save():\n    Path('out.txt').write_text('../etc/passwd')\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-WT",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "CON-WT" and c.status == "FAIL" for c in result.checks)


def test_exception_suppresses_warn_check():
    contract = replace(
        base_contract(),
        exceptions=(
            ExceptionV1(
                id="EXC-WARN",
                rule_id="DEP-001",
                path="src/domain/legacy.py",
                reason="Temporary warn suppression",
                approved_by="lead_architect",
            ),
        ),
    )
    warn_check = CheckResult(
        check_id="dep-warn-1",
        rule_id="DEP-001",
        type="dependency_rule",
        severity="warn",
        status="WARN",
        message="Forbidden dependency (warn)",
        source_path="src/domain/legacy.py",
        target_path="src/adapters/db.py",
    )
    adjusted = apply_exceptions(contract, [warn_check])
    assert len(adjusted) == 1
    assert adjusted[0].status == "PASS"
    assert "EXC-WARN" in adjusted[0].message
    assert overall_status(adjusted) == "PASS"


def test_exception_matches_via_target_path_fallback():
    contract = replace(
        base_contract(),
        exceptions=(
            ExceptionV1(
                id="EXC-TGT",
                rule_id="DEP-001",
                path="src/adapters/db.py",
                reason="Target-side exception",
                approved_by="lead_architect",
            ),
        ),
    )
    fail_check = CheckResult(
        check_id="dep-fail-1",
        rule_id="DEP-001",
        type="dependency_rule",
        severity="block",
        status="FAIL",
        message="Forbidden dependency",
        source_path="src/domain/legacy.py",
        target_path="src/adapters/db.py",
    )
    adjusted = apply_exceptions(contract, [fail_check])
    assert adjusted[0].status == "PASS"
    assert "EXC-TGT" in adjusted[0].message


def test_exception_does_not_suppress_when_neither_path_matches():
    contract = replace(
        base_contract(),
        exceptions=(
            ExceptionV1(
                id="EXC-OTHER",
                rule_id="DEP-001",
                path="src/domain/other.py",
                reason="Unrelated path",
                approved_by="lead_architect",
            ),
        ),
    )
    fail_check = CheckResult(
        check_id="dep-fail-2",
        rule_id="DEP-001",
        type="dependency_rule",
        severity="block",
        status="FAIL",
        message="Forbidden dependency",
        source_path="src/domain/legacy.py",
        target_path="src/adapters/db.py",
    )
    adjusted = apply_exceptions(contract, [fail_check])
    assert adjusted[0].status == "FAIL"
    assert overall_status(adjusted) == "FAIL"


def test_forbid_pattern_warn_severity_does_not_fail_overall(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="SEC-WARN",
            type="forbid_pattern",
            pattern=r"subprocess\.call\(.*shell\s*=\s*True",
            severity="warn",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    warn_checks = [c for c in result.checks if c.status == "WARN"]
    assert warn_checks
    assert all(c.severity == "warn" for c in warn_checks)


def test_max_module_fanout_warn_severity_when_exceeded(tmp_path: Path):
    for name in ("a", "b", "c"):
        _write(tmp_path / "src" / "domain" / f"{name}.py", f"VALUE_{name.upper()} = 1\n")
    _write(
        tmp_path / "src" / "application" / "hub.py",
        "from src.domain import a\nfrom src.domain import b\nfrom src.domain import c\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-WARN",
            type="max_module_fanout",
            severity="warn",
            scope=("src/application/**",),
            params={"max_fanout": 2},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(c.status == "WARN" and "fanout" in c.message.lower() for c in result.checks)


def test_allowlisted_dependencies_warn_severity(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\nimport httpx\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW-WARN",
            type="allowlisted_dependencies_only",
            severity="warn",
            scope=("src/**",),
            params={"allowlist": ["fastapi"]},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(c.status == "WARN" and "httpx" in c.message for c in result.checks)


def test_max_module_fanout_rejects_missing_param(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-CFG",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("max_fanout" in c.message and c.status == "FAIL" for c in result.checks)


def test_max_module_fanout_rejects_negative(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-NEG",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={"max_fanout": -1},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any("non-negative" in c.message.lower() or "max_fanout" in c.message for c in result.checks)


def test_max_module_fanout_rejects_non_integer(tmp_path: Path):
    _write(tmp_path / "src" / "domain" / "a.py", "A = 1\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-FAN-STR",
            type="max_module_fanout",
            severity="block",
            scope=("src/**",),
            params={"max_fanout": "two"},
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.status == "FAIL" and "max_fanout" in c.message for c in result.checks)


def test_allowlisted_dependencies_rejects_non_list_allowlist(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "api.py", "import fastapi\n")
    contract = base_contract(
        ConstraintV1(
            id="CON-ALLOW-CFG",
            type="allowlisted_dependencies_only",
            severity="block",
            scope=("src/**",),
            params={"allowlist": "fastapi"},  # must be a list
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(
        c.status == "FAIL" and "allowlist" in c.message.lower() for c in result.checks
    )


def test_no_path_traversal_allows_read_only_open_with_dotdot(tmp_path: Path):
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "def load(name):\n    return open('../data/' + name, 'r').read()\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-TRAV-READ",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "PASS"
    assert any(c.rule_id == "CON-TRAV-READ" and c.status == "PASS" for c in result.checks)


def test_no_path_traversal_detects_write_text(tmp_path: Path):
    # '..' must appear as a string constant in write_text args (detector walks call args)
    _write(
        tmp_path / "src" / "adapters" / "files.py",
        "from pathlib import Path\n\ndef save():\n    Path('out').write_text('../etc/passwd')\n",
    )
    contract = base_contract(
        ConstraintV1(
            id="CON-TRAV-WT",
            type="no_path_traversal_writes",
            severity="block",
            scope=("src/**",),
        )
    )
    result = evaluate_constraints(contract, tmp_path)
    assert result.status == "FAIL"
    assert any(c.rule_id == "CON-TRAV-WT" and c.status == "FAIL" for c in result.checks)


def test_exception_does_not_suppress_unmatched_path():
    contract = base_contract()
    contract = ArchitectureContractV1(
        schema_version=contract.schema_version,
        contract_id=contract.contract_id,
        version=contract.version,
        status=contract.status,
        project_name=contract.project_name,
        style=contract.style,
        layers=contract.layers,
        dependency_rules=contract.dependency_rules,
        quality_gates=contract.quality_gates,
        constraints=contract.constraints,
        exceptions=(
            ExceptionV1(
                id="EXC-OTHER",
                rule_id="DEP-001",
                path="src/domain/other.py",
                reason="Different path",
                approved_by="lead_architect",
            ),
        ),
    )
    fail_check = CheckResult(
        check_id="dep-fail-2",
        rule_id="DEP-001",
        type="dependency_rule",
        severity="block",
        status="FAIL",
        message="Forbidden dependency",
        source_path="src/domain/legacy.py",
        target_path="src/adapters/db.py",
    )
    adjusted = apply_exceptions(contract, [fail_check])
    assert adjusted[0].status == "FAIL"
    assert overall_status(adjusted) == "FAIL"
