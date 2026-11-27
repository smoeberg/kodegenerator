"""Completion plan step 5: the task compiler.

Contracts become work packages: a contract foundation first, then one
package per module that builds against the contracts in parallel. The
compiler is deterministic and derives day sprints, the critical path and a
scaling plan for the project manager.
"""

from __future__ import annotations

import copy

import pytest

from execution.pipeline_executors import ContractsExecutor
from execution.task_compiler import (
    FOUNDATION_ID,
    TASK_TYPES,
    TaskCompilerError,
    compile_work_plan,
)
from tests.execution.test_contract_council import (
    ARCHITECTURE,
    KRAVSPEC,
    approve,
    contracts,
    council,
)


def plan(c=None, **kwargs):
    return compile_work_plan(
        c or contracts(),
        workflow_id="wf-1",
        organization_id="org-1",
        contract_fingerprint="c" * 64,
        architecture_fingerprint="a" * 64,
        requirements_fingerprint="d" * 64,
        **kwargs,
    )


def by_id(work_plan):
    return {p["logical_task_id"]: p for p in work_plan["packages"]}


def test_foundation_first_then_modules_in_parallel() -> None:
    work_plan = plan()
    packages = by_id(work_plan)
    assert set(packages) == {FOUNDATION_ID, "module-rules", "module-metrics"}
    assert packages[FOUNDATION_ID]["dependency_ids"] == []
    # metrics consumes rules, but builds against the contract, not the code.
    assert packages["module-metrics"]["dependency_ids"] == [FOUNDATION_ID]
    assert work_plan["sprints"] == [
        {"sprint": 1, "packages": [FOUNDATION_ID]},
        {"sprint": 2, "packages": ["module-metrics", "module-rules"]},
    ]
    assert work_plan["scaling_plan"]["parallel_agents_per_role"] == {
        "coder": 2,
        "code_auditor": 2,
        "context_controller": 2,
    }
    assert work_plan["scaling_plan"]["status"] == "awaiting_approval"


def test_packages_carry_scope_criteria_checks_and_task_type() -> None:
    packages = by_id(plan())
    foundation, rules = packages[FOUNDATION_ID], packages["module-rules"]
    assert foundation["write_scope"]["allowed_paths"] == ["contracts"]
    # The foundation writes a contract test for every criterion (rule 3.4).
    assert foundation["criterion_ids"] == sorted(
        c["id"] for c in contracts()["acceptance_criteria"]
    )
    assert rules["write_scope"]["allowed_paths"] == ["src/rules", "tests/rules"]
    assert rules["criterion_ids"] == ["AC-REG-01-1", "AC-REG-01-2", "AC-REG-02-1"]
    assert {"lint", "tests", "level1", "level2", "security"} <= set(
        rules["required_checks"]
    )
    assert {p["task_type"] for p in packages.values()} <= set(TASK_TYPES)
    assert rules["task_type"] == "module_http"


def test_critical_path_is_the_heaviest_chain() -> None:
    work_plan = plan()
    # Foundation (2 modules) -> rules (3 operations + 1 data) is heavier than -> metrics (1).
    assert work_plan["critical_path"] == [FOUNDATION_ID, "module-rules"]
    assert work_plan["scaling_plan"]["critical_path_weight"] == 2 + 4


def test_parallel_limit_splits_a_layer_into_more_sprints() -> None:
    work_plan = plan(max_parallel_packages=1)
    assert [s["packages"] for s in work_plan["sprints"]] == [
        [FOUNDATION_ID],
        ["module-metrics"],
        ["module-rules"],
    ]


def test_overlapping_scopes_are_serialized_not_parallel() -> None:
    c = copy.deepcopy(contracts())
    c["modules"][1]["owned_paths"] = ["src/rules/metrics"]
    packages = by_id(plan(c))
    # The synthesizer orders by id and serializes the later one after the earlier.
    assert packages["module-rules"]["dependency_ids"] == [
        FOUNDATION_ID,
        "module-metrics",
    ]
    assert len(plan(c)["sprints"]) == 3


def test_module_writing_into_the_foundation_fails_closed() -> None:
    c = copy.deepcopy(contracts())
    c["modules"][0]["owned_paths"] = ["contracts/rules"]
    with pytest.raises(TaskCompilerError, match="contract foundation"):
        plan(c)


def test_data_only_module_gets_the_criteria_of_its_requirements() -> None:
    c = copy.deepcopy(contracts())
    c["modules"][1]["provides"] = []
    packages = by_id(plan(c))
    assert packages["module-metrics"]["task_type"] == "module_data"
    assert packages["module-metrics"]["criterion_ids"] == ["AC-REG-03-1"]


def test_plan_is_deterministic_and_fingerprinted() -> None:
    assert plan()["fingerprint"] == plan()["fingerprint"]
    assert plan()["fingerprint"] != plan(max_parallel_packages=1)["fingerprint"]


def test_contracts_step_returns_the_work_plan_with_the_contracts() -> None:
    c, _, _ = council([contracts()], [approve()])
    payload = {
        "architecture": {
            "council": {"proposal": ARCHITECTURE, "proposal_fingerprint": "a" * 64}
        },
        "requirements": KRAVSPEC,
        "requirements_ref": {"fingerprint": "d" * 64},
        "workflow_id": "wf-1",
        "organization_id": "org-1",
        "task_id": "t-1",
    }
    result = ContractsExecutor(council_factory=lambda p: c).execute(payload)
    assert (
        result["work_plan"]["contract_fingerprint"]
        == result["contracts"]["contract_fingerprint"]
    )
    assert len(result["work_plan"]["sprints"]) == 2


def test_no_work_plan_from_contracts_that_fail_the_fact_check() -> None:
    broken = copy.deepcopy(contracts())
    broken["modules"][1]["owned_paths"] = ["src/rules"]
    c, _, _ = council([broken] * 3, [approve()] * 3)
    payload = {
        "architecture": {
            "council": {"proposal": ARCHITECTURE, "proposal_fingerprint": "a" * 64}
        },
        "requirements": KRAVSPEC,
        "workflow_id": "wf-1",
        "organization_id": "org-1",
        "task_id": "t-1",
    }
    result = ContractsExecutor(council_factory=lambda p: c).execute(payload)
    assert result["contracts"]["council"]["status"] == "disagreement"
    assert result["work_plan"] is None
