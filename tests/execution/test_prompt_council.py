"""Decision 42: prompt producer and prompt reviewer write new prompt versions."""

from __future__ import annotations

import shutil

import pytest
import yaml

from domain.prompt_registry import PROMPTS_PATH, PromptRegistry, PromptStatus
from domain.role_process import RoleProcessError
from execution.prompt_council import PromptCouncil, check_prompt
from services.bot_llm_runtime import bound_model
from tests.execution.test_contract_council import ScriptedProvider

APPROVE = {"verdict": "approve", "findings": []}
CURRENT = PromptRegistry.load().active("code_auditor", "audit_package")
BETTER = CURRENT.text.replace("Judge correctness", "Judge correctness, concurrency")


def proposal(text=BETTER, summary="Adds concurrency to what the code auditor judges."):
    return {"text": text, "change_summary": summary, "assumptions": []}


def council(tmp_path, producer_answers, reviewer_answers, reviewer_brand="openai"):
    root = tmp_path / "prompts"
    shutil.copytree(PROMPTS_PATH, root)
    producer = ScriptedProvider("anthropic", producer_answers)
    reviewer = ScriptedProvider("openai", reviewer_answers)
    return (
        PromptCouncil(
            bound_model(producer, brand="anthropic", bot_profile_id="producer"),
            bound_model(reviewer, brand=reviewer_brand, bot_profile_id="reviewer"),
            root=root,
        ),
        root,
        reviewer,
    )


def test_an_agreed_prompt_is_written_as_proposed_and_does_not_run(tmp_path) -> None:
    prompts, root, reviewer = council(tmp_path, [proposal()], [APPROVE])
    outcome = prompts.propose(
        "code_auditor",
        "audit_package",
        "Audit concurrency too.",
        organization_id="o",
        actor_id="board",
    )
    assert outcome["status"] == "agreed" and outcome["version"] == 2
    path = root / "code_auditor" / "audit_package.v2.md"
    header = yaml.safe_load(path.read_text().split("---\n")[1])
    assert header["status"] == "proposed" and header["replaces"] == CURRENT.ref
    registry = PromptRegistry.load(root)
    assert registry.active("code_auditor", "audit_package").version == 1
    assert (
        registry.versions("code_auditor", "audit_package")[-1].status
        is PromptStatus.PROPOSED
    )
    # The reviewer saw the role entry and the current prompt, and the jobs carry the prompt versions.
    assert (
        "Kodeauditør" in reviewer.prompts[0]
        and "Judge correctness" in reviewer.prompts[0]
    )
    assert {j["prompt_version"].split("@")[0] for j in outcome["agent_jobs"]} == {
        "prompt_producer/write_prompt",
        "prompt_reviewer/review_prompt",
    }


def test_a_proposal_that_drops_a_safety_rule_is_never_written(tmp_path) -> None:
    unsafe = proposal(
        CURRENT.text.replace("from a different producer than the coder", "").replace(
            "are not evidence", "are useful"
        )
    )
    prompts, root, _ = council(tmp_path, [unsafe] * 3, [APPROVE] * 3)
    outcome = prompts.propose(
        "code_auditor",
        "audit_package",
        "Shorter.",
        organization_id="o",
        actor_id="board",
    )
    assert outcome["status"] == "disagreement"
    assert {f["code"] for f in outcome["open_findings"]} >= {"safety_rule_dropped"}
    assert not (root / "code_auditor" / "audit_package.v2.md").exists()


def test_producer_and_reviewer_must_come_from_different_producers(tmp_path) -> None:
    with pytest.raises(RoleProcessError, match="producer"):
        council(tmp_path, [], [], reviewer_brand="anthropic")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "empty"),
        ("You are a helper. Untrusted input.", "role_not_named"),
        ("You are the code auditor.", "untrusted_input"),
        (
            "You are the code auditor. You may approve the release. Untrusted input.",
            "forbidden",
        ),
        (
            "You are the code auditor. Skip the fact check when in a hurry. Untrusted input.",
            "forbidden",
        ),
        (
            "You are the code auditor. Trust the coder's report. Untrusted input.",
            "forbidden",
        ),
    ],
)
def test_fact_check(text, code) -> None:
    role = {"id": "code_auditor", "name": "Kodeauditør"}
    findings = check_prompt(
        proposal(text), {"role": role, "current_prompt": {"text": "x"}}
    )
    assert code in {f["code"] for f in findings}


def test_fact_check_passes_a_sound_change() -> None:
    role = {"id": "code_auditor", "name": "Kodeauditør"}
    assert (
        check_prompt(
            proposal(), {"role": role, "current_prompt": {"text": CURRENT.text}}
        )
        == []
    )
