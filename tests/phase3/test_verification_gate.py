from __future__ import annotations

from dataclasses import replace

import pytest

from domain.agent_contract import AGENT_ROLES, AgentContract, AgentContractPackage
from domain.distribution import DispatchRequest, route
from domain.verification import DeliveredProduct, Evidence, VerificationError
from services.verification_service import VerificationService


REQ_FP = "r" * 64
ARCH_FP = "a" * 64
ART_FP = "p" * 64


def make_package() -> AgentContractPackage:
    contracts = tuple(
        AgentContract(
            schema_version="0.1",
            contract_id=f"agent-{role}-v0.1",
            role=role,
            objective=f"Execute {role} work within the contract.",
            source_requirements_fingerprint=REQ_FP,
            source_architecture_fingerprint=ARCH_FP,
            required_inputs=("requirements_contract", "architecture_contract", "approved_task"),
            permitted_outputs=("report", "artifact"),
            forbidden_actions=("bypassing gates",),
            acceptance_criteria_ids=("FR-001",),
            instructions=("Use only supplied contract inputs.",),
        )
        for role in AGENT_ROLES
    )
    return AgentContractPackage(
        schema_version="0.1",
        package_id="verification-package-test",
        requirements_fingerprint=REQ_FP,
        architecture_fingerprint=ARCH_FP,
        contracts=contracts,
    )


def make_dispatch():
    package = make_package()
    request = DispatchRequest(
        package_fingerprint=package.fingerprint,
        role="development",
        available_inputs=("requirements_contract", "architecture_contract", "approved_task"),
        task_id="TASK-20-001",
        task_fingerprint="t" * 64,
    )
    return route(package, request)


def evidence(dispatch, kind: str, passed: bool = True) -> Evidence:
    return Evidence(
        kind=kind,
        evidence_id=f"E-{kind}",
        passed=passed,
        statement=f"{kind} evidence",
        package_fingerprint=dispatch.package_fingerprint,
        contract_fingerprint=dispatch.contract_fingerprint,
        dispatch_fingerprint=dispatch.fingerprint,
        artifact_fingerprint=ART_FP,
    )


def make_product(dispatch, evidence_items=None) -> DeliveredProduct:
    return DeliveredProduct(
        artifact_id="artifact-001",
        artifact_fingerprint=ART_FP,
        output_names=("report",),
        evidence=tuple(evidence_items or [evidence(dispatch, kind) for kind in ("test", "audit", "security", "provenance")]),
    )


def test_pass_requires_independent_evidence_and_exact_bindings() -> None:
    dispatch = make_dispatch()
    result = VerificationService().verify(dispatch, make_product(dispatch))
    assert result.status == "PASS"
    assert not result.failures
    assert result.package_fingerprint == dispatch.package_fingerprint
    assert result.contract_fingerprint == dispatch.contract_fingerprint
    assert result.dispatch_fingerprint == dispatch.fingerprint
    assert result.artifact_fingerprint == ART_FP
    assert result.fingerprint


def test_verification_is_deterministic() -> None:
    dispatch = make_dispatch()
    product = make_product(dispatch)
    first = VerificationService().verify(dispatch, product)
    second = VerificationService().verify(dispatch, product)
    assert first == second
    assert first.fingerprint == second.fingerprint


def test_missing_test_evidence_fails_closed() -> None:
    dispatch = make_dispatch()
    product = make_product(dispatch, [evidence(dispatch, kind) for kind in ("audit", "security", "provenance")])
    result = VerificationService().verify(dispatch, product)
    assert result.status == "FAIL"
    assert any("Required test evidence" in failure for failure in result.failures)


def test_failed_security_evidence_fails_closed() -> None:
    dispatch = make_dispatch()
    product = make_product(dispatch, [evidence(dispatch, "test"), evidence(dispatch, "audit"), evidence(dispatch, "security", False), evidence(dispatch, "provenance")])
    result = VerificationService().verify(dispatch, product)
    assert result.status == "FAIL"
    assert any("Required security evidence" in failure for failure in result.failures)


def test_evidence_with_wrong_dispatch_fingerprint_fails_closed() -> None:
    dispatch = make_dispatch()
    bad = replace(evidence(dispatch, "test"), dispatch_fingerprint="x" * 64)
    product = make_product(dispatch, [bad, evidence(dispatch, "audit"), evidence(dispatch, "security"), evidence(dispatch, "provenance")])
    result = VerificationService().verify(dispatch, product)
    assert result.status == "FAIL"
    assert any("bound to the exact dispatch" in failure for failure in result.failures)


def test_unpermitted_output_fails_closed() -> None:
    dispatch = make_dispatch()
    product = replace(make_product(dispatch), output_names=("secret_output",))
    result = VerificationService().verify(dispatch, product)
    assert result.status == "FAIL"
    assert any("contract-permitted outputs" in failure for failure in result.failures)


def test_artifact_fingerprint_mismatch_in_evidence_fails_closed() -> None:
    dispatch = make_dispatch()
    bad = replace(evidence(dispatch, "test"), artifact_fingerprint="x" * 64)
    product = make_product(dispatch, [bad, evidence(dispatch, "audit"), evidence(dispatch, "security"), evidence(dispatch, "provenance")])
    result = VerificationService().verify(dispatch, product)
    assert result.status == "FAIL"
    assert any("bound to the exact dispatch and artifact" in failure for failure in result.failures)


def test_invalid_product_type_is_rejected() -> None:
    dispatch = make_dispatch()
    with pytest.raises(VerificationError):
        VerificationService().verify(dispatch, object())


def test_verification_id_changes_with_artifact() -> None:
    dispatch = make_dispatch()
    first = VerificationService().verify(dispatch, make_product(dispatch))
    second_product = replace(make_product(dispatch), artifact_fingerprint="q" * 64)
    second = VerificationService().verify(dispatch, second_product)
    assert first.verification_id != second.verification_id
