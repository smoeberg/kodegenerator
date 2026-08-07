from __future__ import annotations

from dataclasses import replace

import pytest

from domain.agent_contract import AGENT_ROLES, AgentContract, AgentContractPackage
from domain.distribution import DispatchRequest, DistributionError, route


REQ_FP = "r" * 64
ARCH_FP = "a" * 64


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
            permitted_outputs=("report",),
            forbidden_actions=("bypassing gates",),
            acceptance_criteria_ids=("FR-001",),
            instructions=("Use only supplied contract inputs.",),
        )
        for role in AGENT_ROLES
    )
    return AgentContractPackage(
        schema_version="0.1",
        package_id="contract-package-test",
        requirements_fingerprint=REQ_FP,
        architecture_fingerprint=ARCH_FP,
        contracts=contracts,
    )


def request(package: AgentContractPackage, role: str = "development") -> DispatchRequest:
    return DispatchRequest(
        package_fingerprint=package.fingerprint,
        role=role,
        available_inputs=("requirements_contract", "architecture_contract", "approved_task"),
        task_id="TASK-001",
        task_fingerprint="t" * 64,
    )


def test_routes_only_to_requested_compiled_role() -> None:
    package = make_package()
    record = route(package, request(package, "test"))
    assert record.selected_role == "test"
    assert record.contract_id == "agent-test-v0.1"
    assert record.package_fingerprint == package.fingerprint
    assert record.contract_fingerprint == next(c for c in package.contracts if c.role == "test").fingerprint


def test_route_is_deterministic() -> None:
    package = make_package()
    first = route(package, request(package, "audit"))
    second = route(package, request(package, "audit"))
    assert first == second
    assert first.fingerprint == second.fingerprint


def test_package_fingerprint_mismatch_fails_closed() -> None:
    package = make_package()
    bad = replace(request(package), package_fingerprint="x" * 64)
    with pytest.raises(DistributionError, match="Package fingerprint"):
        route(package, bad)


def test_unknown_role_fails_closed() -> None:
    package = make_package()
    bad = replace(request(package), role="unknown")
    with pytest.raises(DistributionError, match="exactly one contract"):
        route(package, bad)


def test_missing_required_input_fails_closed() -> None:
    package = make_package()
    bad = replace(request(package), available_inputs=("requirements_contract",))
    with pytest.raises(DistributionError, match="Required dispatch inputs"):
        route(package, bad)


def test_dispatch_binds_task_identity() -> None:
    package = make_package()
    record = route(package, request(package))
    assert record.task_id == "TASK-001"
    assert record.task_fingerprint == "t" * 64


def test_dispatch_does_not_rewrite_contract_inputs_or_outputs() -> None:
    package = make_package()
    contract = next(c for c in package.contracts if c.role == "development")
    record = route(package, request(package))
    assert record.required_inputs == contract.required_inputs
    assert record.permitted_outputs == contract.permitted_outputs


def test_dispatch_id_changes_when_task_fingerprint_changes() -> None:
    package = make_package()
    first = route(package, request(package))
    second = route(package, replace(request(package), task_fingerprint="u" * 64))
    assert first.dispatch_id != second.dispatch_id


def test_dispatch_id_changes_when_role_changes() -> None:
    package = make_package()
    first = route(package, request(package, "development"))
    second = route(package, request(package, "security"))
    assert first.dispatch_id != second.dispatch_id


def test_dispatch_record_has_stable_schema_version() -> None:
    package = make_package()
    record = route(package, request(package))
    assert record.schema_version == "0.1"
