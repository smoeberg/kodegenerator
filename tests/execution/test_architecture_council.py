"""Completion plan step 3: the architecture council.

An architect proposes, an architecture reviewer from a different producer
challenges, the architect revises. A deterministic fact check verifies both.
Disagreement is recorded and goes to the gate; it is never smoothed over.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import pytest

from domain.agent_job import AgentJobStatus
from domain.pipeline_states import PipelineState
from domain.role_process import RoleProcessError
from execution.architecture_council import (
    ArchitectureCouncil,
    ArchitectureCouncilError,
    check_proposal,
    check_review,
    independent_modules,
)
from execution.pipeline_executors import (
    ArchitectureExecutor,
    default_architecture_council,
)
from runtime.pipeline_orchestrator import PipelineOrchestrator
from services.bot_llm_runtime import (
    BotModelResolutionError,
    bound_model,
    resolve_bot_model,
)
from services.llm_adapters import LLMResponse

KRAVSPEC = {
    "project_name": "husregel-register",
    "project_description": "Register",
    "version": "1.0",
    "requirements": [
        {"id": "REG-01", "description": "Rules", "acceptance_criteria": ["a"]},
        {"id": "REG-02", "description": "Versions", "acceptance_criteria": ["b"]},
        {"id": "REG-03", "description": "Measurements", "acceptance_criteria": ["c"]},
    ],
}


def proposal(*, cover_reg03: bool = True, unknown_ref: bool = False) -> dict[str, Any]:
    modules = [
        {
            "id": "rules",
            "responsibility": "Rule store",
            "requirement_ids": ["REG-01", "REG-02"],
            "depends_on": [],
            "interfaces": [
                {"name": "RuleStore", "kind": "port", "description": "CRUD"}
            ],
        },
        {
            "id": "api",
            "responsibility": "HTTP API",
            "requirement_ids": ["REG-01"] + (["REG-99"] if unknown_ref else []),
            "depends_on": ["rules"],
            "interfaces": [{"name": "/rules", "kind": "http", "description": "REST"}],
        },
    ]
    if cover_reg03:
        modules.append(
            {
                "id": "metrics",
                "responsibility": "Measurements",
                "requirement_ids": ["REG-03"],
                "depends_on": ["rules"],
                "interfaces": [
                    {"name": "MetricStore", "kind": "port", "description": "Record"}
                ],
            }
        )
    return {
        "stack": {
            "language": "python",
            "framework": "fastapi",
            "persistence": "postgresql",
            "rationale": "C-01",
        },
        "modules": modules,
        "decisions": [
            {
                "id": "D1",
                "decision": "Hexagonal",
                "rationale": "Testability",
                "requirement_ids": ["REG-01"],
            }
        ],
        "assumptions": [],
    }


def review(verdict: str, *findings: dict[str, Any]) -> dict[str, Any]:
    return {"verdict": verdict, "findings": list(findings)}


def finding(
    fid: str, severity: str, target: str = "api", reqs=("REG-01",)
) -> dict[str, Any]:
    return {
        "id": fid,
        "severity": severity,
        "target": target,
        "issue": "x",
        "requirement_ids": list(reqs),
    }


class ScriptedProvider:
    """A structured provider that answers from a script and records prompts."""

    def __init__(
        self, provider: str, model: str, answers: list[dict[str, Any]]
    ) -> None:
        self.provider, self.model = provider, model
        self.answers = list(answers)
        self.prompts: list[str] = []

    def generate(
        self, prompt: str, schema: Mapping[str, Any], temperature: float = 0.0
    ) -> LLMResponse:
        self.prompts.append(prompt)
        text = json.dumps(self.answers.pop(0))
        return LLMResponse(
            text, self.model, 100, 50, 150, {}, request_id=f"req-{len(self.prompts)}"
        )


def council(
    architect_answers,
    reviewer_answers,
    *,
    architect_brand="anthropic",
    reviewer_brand="openai",
    max_revisions=2,
):
    architect = ScriptedProvider("anthropic", "claude-x", architect_answers)
    reviewer = ScriptedProvider("openai", "gpt-x", reviewer_answers)
    return (
        ArchitectureCouncil(
            bound_model(
                architect, brand=architect_brand, bot_profile_id="architect-bot"
            ),
            bound_model(reviewer, brand=reviewer_brand, bot_profile_id="reviewer-bot"),
            max_revisions=max_revisions,
        ),
        architect,
        reviewer,
    )


def run(c: ArchitectureCouncil, key: str = "task-1") -> dict[str, Any]:
    return c.run(KRAVSPEC, organization_id="org-1", actor_id="owner", run_key=key)


# --------------------------------------------------------------------- #
# Fact check
# --------------------------------------------------------------------- #
def test_fact_check_finds_uncovered_unknown_and_cyclic() -> None:
    ids = ["REG-01", "REG-02", "REG-03"]
    assert check_proposal(proposal(), ids) == []
    codes = {
        f["code"]
        for f in check_proposal(proposal(cover_reg03=False, unknown_ref=True), ids)
    }
    assert codes == {"uncovered_requirement", "unknown_requirement"}
    cyclic = proposal()
    cyclic["modules"][0]["depends_on"] = ["api"]
    assert "dependency_cycle" in {f["code"] for f in check_proposal(cyclic, ids)}


def test_build_layers_show_what_can_be_built_in_parallel() -> None:
    assert independent_modules(proposal()) == [["rules"], ["api", "metrics"]]


def test_reviewer_findings_are_fact_checked_too() -> None:
    verified, rejected = check_review(
        review(
            "revise",
            finding("F1", "major"),
            finding("F2", "major", target="ghost"),
            finding("F3", "minor", reqs=("REG-77",)),
        ),
        proposal(),
        ["REG-01", "REG-02", "REG-03"],
    )
    assert [f["id"] for f in verified] == ["F1"]
    assert {f["id"] for f in rejected} == {"F2", "F3"}
    assert all(f["rejected_because"] for f in rejected)


# --------------------------------------------------------------------- #
# Dialogue
# --------------------------------------------------------------------- #
def test_agreement_in_first_round() -> None:
    c, _, _ = council([proposal()], [review("approve")])
    outcome = run(c)
    assert outcome["status"] == "agreed"
    assert len(outcome["rounds"]) == 1
    assert [j["role"] for j in outcome["agent_jobs"]] == [
        "architect",
        "architecture_reviewer",
    ]
    assert outcome["build_layers"] == [["rules"], ["api", "metrics"]]


def test_revision_answers_findings_and_converges() -> None:
    revised = {
        **proposal(),
        "responses_to_findings": [
            {"finding_id": "F1", "response": "fixed", "accepted": True}
        ],
    }
    c, architect, _ = council(
        [proposal(cover_reg03=False), revised],
        [review("revise", finding("F1", "major")), review("approve")],
    )
    outcome = run(c)
    assert outcome["status"] == "agreed"
    assert len(outcome["rounds"]) == 2
    first = outcome["rounds"][0]
    assert {f["code"] for f in first["fact_check"]} == {"uncovered_requirement"}
    # The architect's second turn received the open findings, both sources.
    second_prompt = architect.prompts[1]
    assert '"F1"' in second_prompt  # the reviewer's finding
    assert '"FC-1"' in second_prompt  # the fact check's finding
    assert outcome["rounds"][1]["responses_to_findings"][0]["finding_id"] == "F1"


def test_disagreement_after_max_revisions_is_recorded_not_smoothed() -> None:
    c, _, _ = council(
        [proposal()] * 3,
        [review("revise", finding("F1", "blocking"))] * 3,
    )
    outcome = run(c)
    assert outcome["status"] == "disagreement"
    assert len(outcome["rounds"]) == 3
    assert [f["id"] for f in outcome["open_findings"]] == ["F1"]


def test_reviewer_approval_does_not_override_the_fact_check() -> None:
    """Agreement is not proof."""
    c, _, _ = council([proposal(cover_reg03=False)] * 3, [review("approve")] * 3)
    outcome = run(c)
    assert outcome["status"] == "disagreement"
    # The reviewer approved every time, yet the architect was asked to revise.
    assert len(outcome["rounds"]) == 3
    assert {f["source"] for f in outcome["open_findings"]} == {"fact_check"}
    assert outcome["build_layers"] == []


def test_reviewer_gets_proposal_and_fact_check_not_the_architects_conversation() -> (
    None
):
    c, _, reviewer = council([proposal()], [review("approve")])
    run(c)
    prompt = reviewer.prompts[0]
    assert "fact_check_findings" in prompt and "proposal" in prompt
    assert "review_findings" not in prompt
    assert "previous_proposal" not in prompt


def test_same_producer_cannot_review_its_own_architecture() -> None:
    with pytest.raises(RoleProcessError, match="different producers"):
        council([proposal()], [review("approve")], reviewer_brand="anthropic")


def test_answer_outside_the_schema_fails_closed() -> None:
    c, _, _ = council([{"stack": {}}], [review("approve")])
    with pytest.raises(ArchitectureCouncilError, match="schema"):
        run(c)


def test_every_agent_call_is_a_job_with_its_own_session_and_evidence() -> None:
    c, _, _ = council(
        [proposal(cover_reg03=False), proposal()], [review("revise"), review("approve")]
    )
    jobs = run(c, key="task-9")["agent_jobs"]
    assert [(j["role"], j["round"]) for j in jobs] == [
        ("architect", 1),
        ("architecture_reviewer", 1),
        ("architect", 2),
        ("architecture_reviewer", 2),
    ]
    assert len({j["session_id"] for j in jobs}) == 4
    assert {j["agent"]["brand"] for j in jobs} == {"anthropic", "openai"}
    assert all(j["provenance"]["output_fingerprint"] for j in jobs)
    assert jobs[0]["usage"]["total_tokens"] == 150


# --------------------------------------------------------------------- #
# Pipeline integration
# --------------------------------------------------------------------- #
YAML = """
project_name: husregel-register
project_description: Register
version: "1.0"
requirements:
  - id: REG-01
    description: Rules
    acceptance_criteria: ["a"]
  - id: REG-02
    description: Versions
    acceptance_criteria: ["b"]
  - id: REG-03
    description: Measurements
    acceptance_criteria: ["c"]
"""


class _Runtime:
    def get_workflow(self, *args):
        return None


def _architecture_task(orch: PipelineOrchestrator):
    wid = orch.start_pipeline(YAML, "org-1", "owner")
    workflow = orch._workflows[wid]
    gate = next(g for g in workflow.gates if "requirements" in g.name.lower())
    orch.approve_gate(wid, gate.id, "owner")
    orch.advance_pipeline(wid)
    (task,) = orch.list_tasks(wid)
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


def test_architecture_task_runs_the_council_and_records_every_agent_job() -> None:
    orch = PipelineOrchestrator(_Runtime())
    wid, workflow, task = _architecture_task(orch)
    c, _, _ = council([proposal()], [review("approve")])
    task.result = ArchitectureExecutor(council_factory=lambda payload: c).execute(
        _payload(workflow, task)
    )
    orch.handle_task_completion(task)

    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATED
    council_artifact = workflow.context["architecture"]["council"]
    assert council_artifact["status"] == "agreed"
    assert "agent_jobs" not in workflow.context
    jobs = orch.list_job_records(wid)
    agent_jobs = [j for j in jobs if j.agent.brand]
    assert [(j.role, j.agent.brand) for j in agent_jobs] == [
        ("architect", "anthropic"),
        ("architecture_reviewer", "openai"),
    ]
    assert all(j.status == AgentJobStatus.SUCCEEDED for j in agent_jobs)
    assert all(j.work_package_id == task.id for j in agent_jobs)
    assert agent_jobs[0].requirements.revision == 1
    assert agent_jobs[1].provenance["output_fingerprint"]


def test_reported_jobs_breaking_the_principle_reject_the_result() -> None:
    orch = PipelineOrchestrator(_Runtime())
    _, workflow, task = _architecture_task(orch)
    c, _, _ = council([proposal()], [review("approve")])
    result = ArchitectureExecutor(council_factory=lambda payload: c).execute(
        _payload(workflow, task)
    )
    # Tamper: the reviewer claims to be from the architect's producer.
    result["agent_jobs"][1]["agent"]["brand"] = "anthropic"
    task.result = result
    orch.handle_task_completion(task)

    assert workflow.current_state == PipelineState.ARCHITECTURE_GENERATING
    assert "architecture" not in workflow.context
    assert "different producers" in task.last_error


def test_council_configuration_is_all_or_nothing(monkeypatch) -> None:
    from execution.pipeline_executors import PipelineExecutorConfigurationError

    monkeypatch.delenv("DOR_ARCHITECT_BOT_PROFILE", raising=False)
    monkeypatch.delenv("DOR_ARCHITECTURE_REVIEWER_BOT_PROFILE", raising=False)
    assert default_architecture_council({}) is None
    monkeypatch.setenv("DOR_ARCHITECT_BOT_PROFILE", "architect-bot")
    with pytest.raises(PipelineExecutorConfigurationError):
        default_architecture_council({})


# --------------------------------------------------------------------- #
# Bot Catalog resolution
# --------------------------------------------------------------------- #
def _catalog(**overrides):
    profile = SimpleNamespace(
        deployment_id="dep",
        deployment_revision=1,
        enabled=True,
        prompt_version="arch-v1",
        budget_policy=SimpleNamespace(max_input_tokens=32_000, max_output_tokens=4_096),
    )
    deployment = SimpleNamespace(
        deployment_id="dep",
        connection_id="con",
        connection_version=2,
        status="active",
        structured_output=True,
        model_id="claude-x",
        max_context_tokens=200_000,
        max_output_tokens=8_000,
        revision=1,
    )
    connection = SimpleNamespace(
        connection_id="con",
        enabled=True,
        adapter_type="anthropic",
        brand="anthropic",
        endpoint="https://api.anthropic.com/v1",
    )
    for key, value in overrides.items():
        target, attr = key.split("__")
        setattr(
            {"profile": profile, "deployment": deployment, "connection": connection}[
                target
            ],
            attr,
            value,
        )

    class Catalog:
        def get_profile(self, org, pid, version=None):
            return profile if pid == "architect-bot" else None

        def get_deployment(self, org, did, revision=None):
            return deployment

        def get_connection(self, org, cid, version=None):
            return connection

    return Catalog()


class _Credentials:
    def __init__(self, secret):
        self._secret = secret

    def secret(self, org, connection_id):
        return self._secret


def test_profile_resolves_to_a_bound_model_with_producer_and_budget() -> None:
    model = resolve_bot_model(
        _catalog(), _Credentials("sk-test"), "org-1", "architect-bot"
    )
    assert (model.identity.brand, model.identity.provider, model.identity.model) == (
        "anthropic",
        "anthropic",
        "claude-x",
    )
    assert model.prompt_version == "arch-v1"
    assert (model.max_input_tokens, model.max_output_tokens) == (32_000, 4_096)
    assert "sk-test" not in json.dumps(model.identity.to_dict())


@pytest.mark.parametrize(
    "overrides, secret, message",
    [
        ({"profile__enabled": False}, "k", "disabled"),
        ({"deployment__status": "retired"}, "k", "retired"),
        ({"deployment__structured_output": False}, "k", "structured"),
        ({"connection__enabled": False}, "k", "disabled"),
        ({"connection__adapter_type": "ollama"}, "k", "unsupported"),
        ({}, None, "credential"),
    ],
)
def test_resolution_fails_closed(overrides, secret, message) -> None:
    with pytest.raises(BotModelResolutionError, match=message):
        resolve_bot_model(
            _catalog(**overrides), _Credentials(secret), "org-1", "architect-bot"
        )


def test_unknown_profile_fails_closed() -> None:
    with pytest.raises(BotModelResolutionError, match="not found"):
        resolve_bot_model(_catalog(), _Credentials("k"), "org-1", "ghost-bot")
