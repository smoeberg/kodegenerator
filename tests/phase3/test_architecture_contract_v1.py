"""Tests for Architecture Contract v1 model and dependency-rules evaluator."""
from datetime import datetime, timezone

import pytest

from domain.architecture_contract_v1 import (
    ArchitectureContractV1,
    ArchitectureContractV1Error,
    DependencyRuleV1,
    LayerV1,
    QualityGateV1,
)
from services.architecture_dependency_evaluator import (
    ImportEdge,
    evaluate_dependency_rules,
    resolve_layer_id,
)


def make_hexagonal_contract(status: str = "review") -> ArchitectureContractV1:
    return ArchitectureContractV1(
        schema_version="1.0",
        contract_id="arch-checkout-service",
        version="1.0.0",
        status=status,
        project_name="checkout-service",
        style="hexagonal",
        language="python",
        runtime="python3.12",
        layers=(
            LayerV1(id="domain", path="src/domain/**", framework_independent=True),
            LayerV1(id="application", path="src/application/**", framework_independent=True),
            LayerV1(id="ports", path="src/ports/**"),
            LayerV1(id="adapters", path="src/adapters/**"),
            LayerV1(id="tests", path="tests/**"),
        ),
        dependency_rules=(
            DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=(), severity="block"),
            DependencyRuleV1(
                id="DEP-002",
                source="application",
                may_depend_on=("domain", "ports"),
                severity="block",
            ),
            DependencyRuleV1(
                id="DEP-003",
                source="adapters",
                may_depend_on=("domain", "application", "ports"),
                severity="block",
            ),
            DependencyRuleV1(
                id="DEP-004",
                source="tests",
                may_depend_on=("domain", "application", "ports", "adapters"),
                severity="block",
            ),
        ),
        quality_gates=(
            QualityGateV1(id="QG-dep", type="dependency_rules", required=True),
            QualityGateV1(id="QG-unit", type="command", required=True, command="pytest -q"),
        ),
    )


def test_fingerprint_is_stable_and_ignores_approval_metadata():
    review = make_hexagonal_contract("review")
    approved = review.approve("soeren", datetime(2026, 8, 18, tzinfo=timezone.utc))
    assert review.fingerprint == approved.fingerprint
    assert approved.approval.content_fingerprint == approved.fingerprint
    assert approved.status == "approved"


def test_fingerprint_changes_when_dependency_rule_changes():
    first = make_hexagonal_contract()
    second = ArchitectureContractV1(
        schema_version=first.schema_version,
        contract_id=first.contract_id,
        version=first.version,
        status=first.status,
        project_name=first.project_name,
        style=first.style,
        layers=first.layers,
        dependency_rules=(
            DependencyRuleV1(id="DEP-001", source="domain", may_depend_on=("ports",), severity="block"),
            *first.dependency_rules[1:],
        ),
        quality_gates=first.quality_gates,
        language=first.language,
        runtime=first.runtime,
    )
    assert first.fingerprint != second.fingerprint


def test_roundtrip_dict():
    original = make_hexagonal_contract()
    restored = ArchitectureContractV1.from_dict(original.to_dict())
    assert restored.fingerprint == original.fingerprint
    assert restored.contract_id == original.contract_id
    assert [layer.id for layer in restored.layers] == [layer.id for layer in original.layers]


def test_approve_requires_draft_or_review():
    approved = make_hexagonal_contract().approve("soeren")
    with pytest.raises(ArchitectureContractV1Error, match="Only draft/review"):
        approved.approve("other")


def test_unknown_dependency_target_layer_rejected():
    with pytest.raises(ArchitectureContractV1Error, match="unknown layer"):
        ArchitectureContractV1(
            schema_version="1.0",
            contract_id="arch-x",
            version="1.0.0",
            status="draft",
            project_name="x",
            style="hexagonal",
            layers=(LayerV1(id="domain", path="src/domain/**"),),
            dependency_rules=(
                DependencyRuleV1(
                    id="DEP-001",
                    source="domain",
                    may_depend_on=("missing",),
                    severity="block",
                ),
            ),
            quality_gates=(QualityGateV1(id="QG-dep", type="dependency_rules", required=True),),
        )


def test_resolve_layer_id_prefers_specific_path():
    contract = make_hexagonal_contract()
    assert resolve_layer_id(contract, "src/domain/orders/entity.py") == "domain"
    assert resolve_layer_id(contract, "src/application/create_order.py") == "application"
    assert resolve_layer_id(contract, "src/adapters/api/routes.py") == "adapters"
    assert resolve_layer_id(contract, "tests/test_orders.py") == "tests"
    assert resolve_layer_id(contract, "README.md") is None


def test_evaluator_allows_valid_edges():
    contract = make_hexagonal_contract()
    result = evaluate_dependency_rules(
        contract,
        [
            ImportEdge("src/application/service.py", "src/domain/model.py"),
            ImportEdge("src/adapters/repo.py", "src/application/service.py"),
            ImportEdge("src/domain/a.py", "src/domain/b.py"),
        ],
    )
    assert result.status == "PASS"
    assert result.contract_fingerprint == contract.fingerprint
    assert result.summary["failed"] == 0


def test_evaluator_blocks_domain_to_adapters():
    contract = make_hexagonal_contract()
    result = evaluate_dependency_rules(
        contract,
        [ImportEdge("src/domain/model.py", "src/adapters/db.py")],
    )
    assert result.status == "FAIL"
    assert result.summary["failed"] >= 1
    assert any(c.rule_id == "DEP-001" and c.status == "FAIL" for c in result.checks)


def test_evaluator_fails_unmapped_source_path():
    contract = make_hexagonal_contract()
    result = evaluate_dependency_rules(
        contract,
        [ImportEdge("scripts/tool.py", "src/domain/model.py")],
    )
    assert result.status == "FAIL"
    assert any(c.rule_id == "DEP-UNMAPPED-SOURCE" for c in result.checks)


def test_evaluation_result_dict_has_required_fields():
    contract = make_hexagonal_contract()
    result = evaluate_dependency_rules(contract, [])
    payload = result.to_dict()
    assert payload["schema_version"] == "1.0"
    assert payload["status"] == "PASS"
    assert payload["contract_id"] == contract.contract_id
    assert payload["contract_fingerprint"] == contract.fingerprint
    assert "summary" in payload
    assert payload["summary"]["total"] >= 1
