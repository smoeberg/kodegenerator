"""Tests for formal architecture exceptions in AST-based validation."""
from datetime import datetime, timedelta, timezone
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
from services.architecture_dependency_evaluator import ImportEdge, evaluate_dependency_rules
from services.architecture_exception_policy import apply_exceptions, overall_status
from services.architecture_verification import verify_architecture


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_contract(
    *,
    constraints: tuple[ConstraintV1, ...] = (),
    exceptions: tuple[ExceptionV1, ...] = (),
) -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-exc",
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
        exceptions=exceptions,
    )


def test_exception_suppresses_forbidden_dependency():
    contract = make_contract(
        exceptions=(
            ExceptionV1(
                id="EXC-001",
                rule_id="DEP-001",
                path="src/domain/legacy.py",
                reason="Temporary legacy adapter access",
                approved_by="lead_architect",
            ),
        )
    )
    raw = evaluate_dependency_rules(
        contract,
        [ImportEdge("src/domain/legacy.py", "src/adapters/db.py")],
    )
    assert raw.status == "FAIL"
    adjusted = apply_exceptions(contract, raw.checks)
    assert overall_status(adjusted) == "PASS"
    assert any("EXC-001" in c.message for c in adjusted)


def test_expired_exception_does_not_suppress():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    contract = make_contract(
        exceptions=(
            ExceptionV1(
                id="EXC-002",
                rule_id="DEP-001",
                path="src/domain/legacy.py",
                reason="Expired exception",
                approved_by="lead_architect",
                expires_at=past,
            ),
        )
    )
    raw = evaluate_dependency_rules(
        contract,
        [ImportEdge("src/domain/legacy.py", "src/adapters/db.py")],
    )
    adjusted = apply_exceptions(contract, raw.checks)
    assert overall_status(adjusted) == "FAIL"


def test_exception_in_unified_verification(tmp_path: Path):
    _write(tmp_path / "src" / "adapters" / "db.py", "ENGINE = 'x'\n")
    _write(
        tmp_path / "src" / "domain" / "legacy.py",
        "from src.adapters import db\n",
    )
    contract = make_contract(
        exceptions=(
            ExceptionV1(
                id="EXC-010",
                rule_id="DEP-001",
                path="src/domain/legacy.py",
                reason="Legacy bridge",
                approved_by="lead_architect",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            ),
        )
    )
    result = verify_architecture(contract, tmp_path)
    assert result.status == "PASS"


def test_constraint_exception_and_comment_not_false_positive(tmp_path: Path):
    # Real violation in code
    _write(
        tmp_path / "src" / "adapters" / "run.py",
        "import subprocess\nsubprocess.call('ls', shell=True)\n",
    )
    # Comment-only mention should not alone cause failure in another file
    _write(
        tmp_path / "src" / "domain" / "notes.py",
        "# never use subprocess.call(..., shell=True)\nVALUE = 1\n",
    )
    contract = make_contract(
        constraints=(
            ConstraintV1(
                id="SEC-001",
                type="forbid_pattern",
                pattern=r"subprocess\.call\(.*shell\s*=\s*True",
                severity="block",
                scope=("src/**",),
            ),
        ),
        exceptions=(
            ExceptionV1(
                id="EXC-020",
                rule_id="SEC-001",
                path="src/adapters/run.py",
                reason="Legacy ops script pending rewrite",
                approved_by="security_lead",
            ),
        ),
    )
    result = verify_architecture(contract, tmp_path)
    assert result.status == "PASS"


def test_exceptions_affect_fingerprint():
    base = make_contract()
    with_exc = make_contract(
        exceptions=(
            ExceptionV1(
                id="EXC-001",
                rule_id="DEP-001",
                path="src/domain/legacy.py",
                reason="x",
                approved_by="a",
            ),
        )
    )
    assert base.fingerprint != with_exc.fingerprint
