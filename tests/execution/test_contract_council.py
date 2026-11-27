"""Completion plan step 4: module contracts.

The contract author writes one contract per architecture module; the context
controller, from a different producer, checks them; a deterministic fact
check verifies coverage, interfaces, write scopes and schemas across modules.
OpenAPI and traceability are derived from the contracts.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from typing import Any

import pytest

from domain.agent_job import AgentJobStatus
from domain.pipeline_states import PipelineState
from domain.role_process import RoleProcessError
from execution.contract_council import (
    ContractCouncil,
    build_order,
    check_contracts,
    derive_openapi,
    review_targets,
)
from execution.pipeline_executors import (
    ContractsExecutor,
    PipelineExecutorConfigurationError,
    default_contract_council,
)
from generation.contract_generator import GeneratedContracts
from generation.test_generator import ContractTestGenerator
from runtime.pipeline_orchestrator import PipelineOrchestrator
from services.bot_llm_runtime import bound_model
from services.llm_adapters import LLMResponse

REQS = ["REG-01", "REG-02", "REG-03"]
KRAVSPEC = {
    "project_name": "husregel-register",
    "project_description": "Register",
    "version": "1.0",
    "requirements": [
        {"id": r, "description": r, "acceptance_criteria": ["x"]} for r in REQS
    ],
}
ARCHITECTURE = {
    "stack": {
        "language": "python",
        "framework": "fastapi",
        "persistence": "postgresql",
        "rationale": "C-01",
    },
    "modules": [
        {
            "id": "rules",
            "responsibility": "Store",
            "requirement_ids": ["REG-01", "REG-02"],
            "depends_on": [],
            "interfaces": [],
        },
        {
            "id": "metrics",
            "responsibility": "Measure",
            "requirement_ids": ["REG-03"],
            "depends_on": ["rules"],
            "interfaces": [],
        },
    ],
    "decisions": [],
    "assumptions": [],
}

OBJ = {"type": "object", "properties": {"id": {"type": "string"}}}


def contracts() -> dict[str, Any]:
    return {
        "modules": [
            {
                "module_id": "rules",
                "requirement_ids": ["REG-01", "REG-02"],
                "owned_paths": ["src/rules", "tests/rules"],
                "provides": [
                    {
                        "interface": "RulesApi",
                        "kind": "http",
                        "operations": [
                            {
                                "id": "create",
                                "description": "Create rule",
                                "http": {
                                    "method": "POST",
                                    "path": "/rules",
                                    "success_status": 201,
                                },
                                "input_schema": OBJ,
                                "output_schema": OBJ,
                                "errors": ["409"],
                                "acceptance_criteria": ["AC-REG-01-1"],
                            },
                            {
                                "id": "version",
                                "description": "Get version",
                                "http": {
                                    "method": "GET",
                                    "path": "/rulesets/{v}",
                                    "success_status": 200,
                                },
                                "input_schema": OBJ,
                                "output_schema": OBJ,
                                "errors": [],
                                "acceptance_criteria": ["AC-REG-02-1"],
                            },
                        ],
                    },
                    {
                        "interface": "RuleLookup",
                        "kind": "port",
                        "operations": [
                            {
                                "id": "get",
                                "description": "Lookup",
                                "http": None,
                                "input_schema": OBJ,
                                "output_schema": OBJ,
                                "errors": [],
                                "acceptance_criteria": ["AC-REG-01-2"],
                            },
                        ],
                    },
                ],
                "consumes": [],
                "data": [{"name": "Rule", "schema": OBJ}],
            },
            {
                "module_id": "metrics",
                "requirement_ids": ["REG-03"],
                "owned_paths": ["src/metrics", "tests/metrics"],
                "provides": [
                    {
                        "interface": "MetricsApi",
                        "kind": "http",
                        "operations": [
                            {
                                "id": "record",
                                "description": "Record",
                                "http": {
                                    "method": "POST",
                                    "path": "/measurements",
                                    "success_status": 201,
                                },
                                "input_schema": OBJ,
                                "output_schema": OBJ,
                                "errors": [],
                                "acceptance_criteria": ["AC-REG-03-1"],
                            },
                        ],
                    }
                ],
                "consumes": [{"module_id": "rules", "interface": "RuleLookup"}],
                "data": [],
            },
        ],
        "acceptance_criteria": [
            {
                "id": "AC-REG-01-1",
                "requirement_id": "REG-01",
                "statement": "POST /rules returns 201",
                "verification": "http",
            },
            {
                "id": "AC-REG-01-2",
                "requirement_id": "REG-01",
                "statement": "Lookup by id",
                "verification": "unit",
            },
            {
                "id": "AC-REG-02-1",
                "requirement_id": "REG-02",
                "statement": "GET /rulesets/{v} returns 200",
                "verification": "http",
            },
            {
                "id": "AC-REG-03-1",
                "requirement_id": "REG-03",
                "statement": "POST /measurements returns 201",
                "verification": "http",
            },
        ],
        "assumptions": [],
    }


def codes(findings) -> set[str]:
    return {f["code"] for f in findings}


# --------------------------------------------------------------------- #
# Fact check
# --------------------------------------------------------------------- #
def test_valid_contracts_pass_the_fact_check() -> None:
    assert check_contracts(contracts(), ARCHITECTURE, REQS) == []
    assert build_order(contracts()) == [["rules"], ["metrics"]]


def _mutated(fn) -> dict[str, Any]:
    c = copy.deepcopy(contracts())
    fn(c)
    return c


@pytest.mark.parametrize(
    "mutate, code",
    [
        (lambda c: c["modules"].pop(), "missing_contract"),
        (lambda c: c["modules"][0].update(module_id="ghost"), "unknown_module"),
        (lambda c: c["acceptance_criteria"].pop(), "requirement_without_criteria"),
        (
            lambda c: c["acceptance_criteria"].append(
                {
                    "id": "AC-X",
                    "requirement_id": "REG-01",
                    "statement": "s",
                    "verification": "unit",
                }
            ),
            "criterion_not_carried",
        ),
        (
            lambda c: c["modules"][0].update(requirement_ids=["REG-01"]),
            "dropped_requirement",
        ),
        (
            lambda c: c["modules"][1].update(owned_paths=["src/rules/metrics"]),
            "overlapping_paths",
        ),
        (
            lambda c: c["modules"][1].update(owned_paths=["../escape"]),
            "invalid_owned_path",
        ),
        (
            lambda c: c["modules"][1]["provides"][0]["operations"][0]["http"].update(
                method="POST", path="/rules"
            ),
            "duplicate_route",
        ),
        (
            lambda c: c["modules"][1]["consumes"].append(
                {"module_id": "rules", "interface": "Nope"}
            ),
            "unknown_interface",
        ),
        (
            lambda c: c["modules"][0]["consumes"].append(
                {"module_id": "metrics", "interface": "MetricsApi"}
            ),
            "undeclared_dependency",
        ),
        (
            lambda c: c["modules"][0]["provides"][0]["operations"][0].update(
                input_schema={"type": 12}
            ),
            "invalid_schema",
        ),
        (
            lambda c: c["modules"][0]["provides"][0]["operations"][0].update(http=None),
            "http_without_route",
        ),
        (
            lambda c: c["modules"][0]["provides"][0]["operations"][0].update(
                acceptance_criteria=["AC-NONE"]
            ),
            "unknown_criterion",
        ),
    ],
)
def test_fact_check_catches_each_contract_defect(mutate, code) -> None:
    assert code in codes(check_contracts(_mutated(mutate), ARCHITECTURE, REQS))


def test_review_targets_cover_modules_interfaces_and_criteria() -> None:
    targets = review_targets(contracts())
    assert {
        "general",
        "rules",
        "rules.RulesApi",
        "metrics.MetricsApi",
        "AC-REG-03-1",
    } <= targets


# --------------------------------------------------------------------- #
# Derived OpenAPI and traceability
# --------------------------------------------------------------------- #
def test_openapi_and_traceability_are_derived_from_the_contracts() -> None:
    openapi, http_trace, full_trace = derive_openapi(
        contracts(), title="husregel-register"
    )
    assert set(openapi["paths"]) == {"/rules", "/rulesets/{v}", "/measurements"}
    create = openapi["paths"]["/rules"]["post"]
    assert (
        create["x-criterion-id"] == "AC-REG-01-1" and create["x-module-id"] == "rules"
    )
    assert "201" in create["responses"]
    assert {t["criterion_id"] for t in http_trace} == {
        "AC-REG-01-1",
        "AC-REG-02-1",
        "AC-REG-03-1",
    }
    # The port criterion is traced but not HTTP-tested; step 7 verifies it.
    assert {t["criterion_id"] for t in full_trace} == {
        c["id"] for c in contracts()["acceptance_criteria"]
    }


def test_contract_test_generator_covers_the_derived_contract() -> None:
    openapi, http_trace, _ = derive_openapi(contracts(), title="t")
    suite = ContractTestGenerator().generate(
        GeneratedContracts(openapi, tuple(http_trace), "f")
    )
    assert set(suite.covered_criteria) == {t["criterion_id"] for t in http_trace}


# --------------------------------------------------------------------- #
# Dialogue
# --------------------------------------------------------------------- #
class ScriptedProvider:
    def __init__(self, provider: str, answers: list[dict[str, Any]]) -> None:
        self.provider, self.model = provider, f"{provider}-model"
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate(
        self, prompt: str, schema: Mapping[str, Any], temperature: float = 0.0
    ) -> LLMResponse:
        self.prompts.append(prompt)
        return LLMResponse(
            json.dumps(self.answers.pop(0)), self.model, 10, 5, 15, {}, request_id="r"
        )


def council(author_answers, controller_answers, *, controller_brand="openai"):
    author = ScriptedProvider("anthropic", author_answers)
    controller = ScriptedProvider("openai", controller_answers)
    return (
        ContractCouncil(
            bound_model(author, brand="anthropic", bot_profile_id="author-bot"),
            bound_model(
                controller, brand=controller_brand, bot_profile_id="controller-bot"
            ),
        ),
        author,
        controller,
    )


def approve() -> dict[str, Any]:
    return {"verdict": "approve", "findings": []}


def test_council_agrees_and_derives_the_contract_artifacts() -> None:
    c, _, controller = council([contracts()], [approve()])
    outcome = c.run(
        KRAVSPEC, ARCHITECTURE, organization_id="org-1", actor_id="owner", run_key="t1"
    )
    assert outcome["status"] == "agreed"
    assert outcome["build_layers"] == [["rules"], ["metrics"]]
    assert "/rules" in outcome["openapi"]["paths"]
    assert [j["role"] for j in outcome["agent_jobs"]] == [
        "contract_author",
        "context_controller",
    ]
    prompt = controller.prompts[0]
    assert "approved_architecture" in prompt and "fact_check_findings" in prompt
    assert "review_findings" not in prompt


def test_fact_check_forces_revision_even_when_the_controller_approves() -> None:
    broken = _mutated(lambda c: c["modules"][1].update(owned_paths=["src/rules"]))
    c, author, _ = council(
        [broken, broken, contracts()], [approve(), approve(), approve()]
    )
    outcome = c.run(
        KRAVSPEC, ARCHITECTURE, organization_id="org-1", actor_id="owner", run_key="t2"
    )
    assert outcome["status"] == "agreed"
    assert len(outcome["rounds"]) == 3
    assert "overlapping_paths" in author.prompts[1]


def test_same_producer_cannot_control_its_own_contracts() -> None:
    with pytest.raises(RoleProcessError, match="different producers"):
        council([contracts()], [approve()], controller_brand="anthropic")


# --------------------------------------------------------------------- #
# Pipeline integration
# --------------------------------------------------------------------- #
YAML = "\n".join(
    [
        "project_name: husregel-register",
        "project_description: Register",
        'version: "1.0"',
        "requirements:",
        *[
            f'  - id: {r}\n    description: {r}\n    acceptance_criteria: ["x"]'
            for r in REQS
        ],
    ]
)


class _Runtime:
    def get_workflow(self, *args):
        return None


def _contracts_task(orch: PipelineOrchestrator):
    wid = orch.start_pipeline(YAML, "org-1", "owner")
    workflow = orch._workflows[wid]
    for name in ("requirements", "architecture"):
        gate = next(g for g in workflow.gates if name in g.name.lower())
        if name == "architecture":
            (arch_task,) = orch.list_tasks(wid)
            arch_task.result = {
                "architecture": {
                    "council": {
                        "status": "agreed",
                        "proposal": ARCHITECTURE,
                        "proposal_fingerprint": "a" * 64,
                    }
                }
            }
            orch.handle_task_completion(arch_task)
        orch.approve_gate(wid, gate.id, "owner")
        orch.advance_pipeline(wid)
    task = next(
        t
        for t in orch.list_tasks(wid)
        if (t.metadata or {}).get("task_type") == "generate_contracts"
    )
    return wid, workflow, task


def _payload(workflow, task) -> dict[str, Any]:
    return {
        **workflow.context,
        "context": workflow.context,
        "task_id": task.id,
        "workflow_id": workflow.id,
        "organization_id": "org-1",
        "actor_id": "owner",
    }


def test_contracts_task_runs_the_council_and_records_jobs() -> None:
    orch = PipelineOrchestrator(_Runtime())
    wid, workflow, task = _contracts_task(orch)
    c, _, _ = council([contracts()], [approve()])
    task.result = ContractsExecutor(council_factory=lambda payload: c).execute(
        _payload(workflow, task)
    )
    orch.handle_task_completion(task)

    assert workflow.current_state == PipelineState.CONTRACTS_GENERATED
    stored = workflow.context["contracts"]
    assert stored["council"]["status"] == "agreed"
    assert stored["architecture_fingerprint"] == "a" * 64
    assert {m["module_id"] for m in stored["modules"]} == {"rules", "metrics"}
    jobs = [j for j in orch.list_job_records(wid) if j.agent.brand]
    assert [(j.role, j.agent.brand, j.status) for j in jobs] == [
        ("contract_author", "anthropic", AgentJobStatus.SUCCEEDED),
        ("context_controller", "openai", AgentJobStatus.SUCCEEDED),
    ]


def test_contract_council_requires_a_council_architecture() -> None:
    c, _, _ = council([contracts()], [approve()])
    payload = {"architecture": {"files": []}, "requirements": KRAVSPEC}
    with pytest.raises(ValueError, match="architecture council"):
        ContractsExecutor(council_factory=lambda payload: c).execute(payload)


def test_contract_council_configuration_is_all_or_nothing(monkeypatch) -> None:
    monkeypatch.delenv("DOR_CONTRACT_AUTHOR_BOT_PROFILE", raising=False)
    monkeypatch.delenv("DOR_CONTEXT_CONTROLLER_BOT_PROFILE", raising=False)
    assert default_contract_council({}) is None
    monkeypatch.setenv("DOR_CONTEXT_CONTROLLER_BOT_PROFILE", "controller-bot")
    with pytest.raises(PipelineExecutorConfigurationError):
        default_contract_council({})
