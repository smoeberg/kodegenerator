"""Decision 41: the task producer splits, the compiler checks, the system architect challenges."""

from __future__ import annotations

import copy

import pytest

from domain.pipeline_states import PipelineState
from domain.role_process import RoleProcessError
from execution.pipeline_executors import ContractsExecutor
from execution.task_compiler import TaskCompilerError, check_split, compile_work_plan
from execution.task_council import TaskCouncil
from runtime.pipeline_orchestrator import PipelineOrchestrator
from services.bot_llm_runtime import bound_model
from tests.execution.test_contract_council import (
    KRAVSPEC,
    ScriptedProvider,
    _contracts_task,
    _payload,
    _Runtime,
    approve,
    contracts,
    council,
)

#: The rules module split in two parts with disjoint paths; the store comes first.
SPLIT = {
    "packages": [
        {
            "package_id": "module-rules-store",
            "module_id": "rules",
            "description": "Rule storage and lookup",
            "weight": 3,
            "owned_paths": ["src/rules/store", "tests/rules/store"],
            "criterion_ids": ["AC-REG-01-1", "AC-REG-01-2"],
            "depends_on": [],
        },
        {
            "package_id": "module-rules-versions",
            "module_id": "rules",
            "description": "Rule versions on top of the store",
            "weight": 2,
            "owned_paths": ["src/rules/versions", "tests/rules/versions"],
            "criterion_ids": ["AC-REG-02-1"],
            "depends_on": ["module-rules-store"],
        },
        {
            "package_id": "module-metrics",
            "module_id": "metrics",
            "description": "Record metrics",
            "weight": 1,
            "owned_paths": ["src/metrics", "tests/metrics"],
            "criterion_ids": ["AC-REG-03-1"],
            "depends_on": [],
        },
    ],
    "assumptions": [],
}


def compile_with(split):
    return compile_work_plan(
        contracts(),
        workflow_id="wf",
        organization_id="org",
        contract_fingerprint="c" * 64,
        architecture_fingerprint="a" * 64,
        requirements_fingerprint="d" * 64,
        split=split,
    )


def broken(change):
    split = copy.deepcopy(SPLIT)
    change(split["packages"])
    return split


# --------------------------------------------------------------------- #
# The compiler as fact check
# --------------------------------------------------------------------- #
def test_a_split_compiles_into_packages_sprints_and_a_critical_path() -> None:
    plan = compile_with(SPLIT)
    assert plan["task_split"] == "task_producer"
    packages = {p["logical_task_id"]: p for p in plan["packages"]}
    assert set(packages) == {
        "contract-foundation",
        *(p["package_id"] for p in SPLIT["packages"]),
    }
    assert [s["packages"] for s in plan["sprints"]] == [
        ["contract-foundation"],
        ["module-metrics", "module-rules-store"],
        ["module-rules-versions"],
    ]
    versions = packages["module-rules-versions"]
    assert versions["dependency_ids"] == ["contract-foundation", "module-rules-store"]
    assert versions["requirement_ids"] == ["REG-02"]
    assert versions["description"] == "Rule versions on top of the store"
    assert plan["critical_path"] == [
        "contract-foundation",
        "module-rules-store",
        "module-rules-versions",
    ]
    # Without a split the compiler's default is unchanged: one package per module.
    assert compile_with(None)["task_split"] == "compiler_default"
    assert {p["logical_task_id"] for p in compile_with(None)["packages"]} == {
        "contract-foundation",
        "module-rules",
        "module-metrics",
    }


@pytest.mark.parametrize(
    ("change", "code"),
    [
        (lambda ps: ps.pop(), "module_not_covered"),
        (lambda ps: ps[1]["criterion_ids"].append("AC-REG-01-1"), "criterion_coverage"),
        (lambda ps: ps[1]["criterion_ids"].clear(), "no_criteria"),
        (lambda ps: ps[0]["criterion_ids"].remove("AC-REG-01-2"), "criterion_coverage"),
        (
            lambda ps: ps[0]["owned_paths"].append("src/metrics/x"),
            "path_outside_module",
        ),
        (lambda ps: ps[0]["owned_paths"].append("src/rulesX"), "path_outside_module"),
        (lambda ps: ps[2]["criterion_ids"].append("AC-REG-01-1"), "foreign_criterion"),
        (lambda ps: ps[1]["depends_on"].append("module-ghost"), "unknown_dependency"),
        (lambda ps: ps[0].update(weight=0), "weight"),
        (lambda ps: ps[0].update(weight="3"), "weight"),
        (lambda ps: ps[0].update(package_id="rules store"), "package_id"),
        (lambda ps: ps[1].update(package_id="module-rules-store"), "duplicate_package"),
        (lambda ps: ps[0].update(module_id="ghost"), "unknown_module"),
        (lambda ps: ps[0].update(description=" "), "no_description"),
        (lambda ps: ps[0].update(owned_paths=[]), "no_paths"),
    ],
)
def test_the_compiler_rejects_an_unsafe_split(change, code) -> None:
    split = broken(change)
    c = contracts()
    assert code in {
        f["code"] for f in check_split(split, c["modules"], c["acceptance_criteria"])
    }
    with pytest.raises(TaskCompilerError):
        compile_with(split)


def test_a_dependency_cycle_is_rejected() -> None:
    split = broken(lambda ps: ps[0]["depends_on"].append("module-rules-versions"))
    with pytest.raises(TaskCompilerError, match="cycle|not consistent"):
        compile_with(split)


def test_the_foundation_cannot_be_split_away() -> None:
    split = broken(lambda ps: ps[0].update(owned_paths=["contracts/rules"]))
    with pytest.raises(TaskCompilerError):
        compile_with(split)


# --------------------------------------------------------------------- #
# The dialogue
# --------------------------------------------------------------------- #
def task_council(producer_answers, architect_answers, *, architect_brand="openai"):
    producer = ScriptedProvider("anthropic", producer_answers)
    architect = ScriptedProvider("openai", architect_answers)
    return (
        TaskCouncil(
            bound_model(producer, brand="anthropic", bot_profile_id="task-producer"),
            bound_model(
                architect, brand=architect_brand, bot_profile_id="system-architect"
            ),
        ),
        architect,
    )


def run(c):
    return c.run(
        contracts(),
        {"modules": []},
        KRAVSPEC,
        organization_id="org",
        actor_id="pm",
        run_key="wf",
    )


def test_an_agreed_split_carries_prompt_versions_and_the_architect_sees_the_fact_check() -> (
    None
):
    c, architect = task_council([SPLIT], [approve()])
    outcome = run(c)
    assert outcome["status"] == "agreed"
    assert outcome["proposal"]["packages"] == SPLIT["packages"]
    assert [j["role"] for j in outcome["agent_jobs"]] == [
        "task_producer",
        "system_architect",
    ]
    assert outcome["agent_jobs"][1]["prompt_version"].startswith(
        "system_architect/review_task_split@v1+"
    )
    assert "fact_check_findings" in architect.prompts[0]


def test_a_split_the_compiler_rejects_never_becomes_agreed() -> None:
    bad = broken(lambda ps: ps.pop())
    c, _ = task_council([bad, bad, bad], [approve()] * 3)
    outcome = run(c)
    assert outcome["status"] == "disagreement"
    assert "module_not_covered" in {f.get("code") for f in outcome["open_findings"]}


def test_producer_and_architect_come_from_different_producers() -> None:
    with pytest.raises(RoleProcessError, match="producer"):
        task_council([], [], architect_brand="anthropic")


# --------------------------------------------------------------------- #
# The contracts gate
# --------------------------------------------------------------------- #
def test_the_contracts_gate_gets_the_task_producers_plan(monkeypatch) -> None:
    orch = PipelineOrchestrator(_Runtime())
    wid, workflow, task = _contracts_task(orch)
    contract_council, _, _ = council([contracts()], [approve()])
    tasks, _ = task_council([SPLIT], [approve()])
    task.result = ContractsExecutor(
        council_factory=lambda payload: contract_council,
        task_council_factory=lambda payload: tasks,
    ).execute(_payload(workflow, task))
    orch.handle_task_completion(task)

    assert workflow.current_state == PipelineState.CONTRACTS_GENERATED
    assert task.result["task_council"]["status"] == "agreed"
    assert task.result["work_plan"]["task_split"] == "task_producer"
    roles = [j.role for j in orch.list_job_records(wid) if j.agent.brand]
    assert roles == [
        "contract_author",
        "context_controller",
        "task_producer",
        "system_architect",
    ]


def test_without_an_agreed_split_there_is_no_work_plan() -> None:
    orch = PipelineOrchestrator(_Runtime())
    _, workflow, task = _contracts_task(orch)
    contract_council, _, _ = council([contracts()], [approve()])
    revise = {
        "verdict": "revise",
        "findings": [
            {
                "id": "SA-1",
                "severity": "blocking",
                "target": "general",
                "issue": "no",
                "requirement_ids": [],
            }
        ],
    }
    tasks, _ = task_council([SPLIT] * 3, [revise] * 3)
    result = ContractsExecutor(
        council_factory=lambda payload: contract_council,
        task_council_factory=lambda payload: tasks,
    ).execute(_payload(workflow, task))
    assert result["task_council"]["status"] == "disagreement"
    assert result["work_plan"] is None
