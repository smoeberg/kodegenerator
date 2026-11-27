"""Completion plan step 7: control of a delivered work package.

Fact check (system), level 1 (code auditor) and level 2 (context controller)
from another producer than the coder, and the fixed sorting between rework,
discard-and-rebuild, change of input and the human. The coder is the real
worker adapter with a scripted agent; the factory's own test runs are real.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from execution.package_control import (
    AgentChoice,
    PackageControl,
    PackageControlConfigurationError,
    PackageLine,
    default_package_control,
    triage,
    verify_findings,
)
from execution.task_compiler import compile_work_plan
from execution.worker_adapter import AgentRun, WorkerAdapter
from services.agent_log_store import FileAgentLogStore
from services.bot_llm_runtime import bound_model
from services.factory_workspace import FactoryWorkspaceManager
from tests.execution.test_contract_council import KRAVSPEC, ScriptedProvider, contracts
from tests.execution.test_worker_adapter import git, repository

APPROVE = {"verdict": "approve", "findings": []}

#: The test designer's acceptance tests for the rules module (contract foundation).
RULES_CONTRACT_TESTS = (
    "def test_ac_reg_01_1_contract():\n    from src.rules.store import create\n    assert create({'id': 'x'})['id'] == 'x'\n\n\n"
    "def test_ac_reg_01_2_contract():\n    from src.rules.store import create  # noqa: F401\n\n\n"
    "def test_ac_reg_02_1_contract():\n    from src.rules.store import create  # noqa: F401\n"
)

GOOD_RULES = {
    "src/rules/store.py": "def create(rule):\n    return {'id': rule['id']}\n",
    "tests/rules/test_store.py": (
        "from src.rules.store import create\n\n\n"
        "def test_ac_reg_01_1_creates_a_rule():\n    assert create({'id': 'r'}) == {'id': 'r'}\n\n\n"
        "def test_ac_reg_01_2_lookup():\n    assert True\n\n\n"
        "def test_ac_reg_02_1_version():\n    assert True\n"
    ),
    "src/rules/__init__.py": "",
}


class ScriptedCoder:
    """Stands in for the coding agent: each call writes one set of files."""

    def __init__(self, *deliveries: dict[str, str] | None) -> None:
        self.deliveries = list(deliveries)
        self.prompts: list[str] = []

    def __call__(self, command, prompt, cwd: Path, **_: Any) -> AgentRun:
        self.prompts.append(prompt)
        files = self.deliveries.pop(0)
        if files is None:
            return AgentRun(
                exit_code=1, stream=[], stderr="crashed", duration_seconds=0.1
            )
        for path, text in files.items():
            target = cwd / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        return AgentRun(
            exit_code=0,
            stream=[json.dumps({"type": "result"})],
            stderr="",
            duration_seconds=0.1,
            session_id=f"{command.tool}-{len(self.prompts)}",
        )


@pytest.fixture
def plan():
    return compile_work_plan(
        contracts(),
        workflow_id="wf-1",
        organization_id="org-1",
        contract_fingerprint="c" * 64,
        architecture_fingerprint="a" * 64,
        requirements_fingerprint="d" * 64,
    )


def package(plan, task_id="module-rules"):
    return next(p for p in plan["packages"] if p["logical_task_id"] == task_id)


def finding(target, *, severity="blocking", cause=None, fid="L-1"):
    item = {
        "id": fid,
        "severity": severity,
        "target": target,
        "issue": "wrong",
        "requirement_ids": ["REG-01"],
    }
    if cause:
        item["cause"] = cause
    return item


def line(
    tmp_path,
    coder: ScriptedCoder,
    auditor_answers: list[dict],
    controller_answers: list[dict],
    *,
    auditor_brand="openai",
    controller_brand="openai",
    security_answers: list[dict] | None = None,
    security_brand="openai",
):
    root, base = repository(tmp_path)
    # The contract foundation is merged: the test designer's acceptance tests.
    (root / "contracts").mkdir()
    (root / "contracts" / "test_rules_contract.py").write_text(RULES_CONTRACT_TESTS)
    git(root, "add", ".")
    git(root, "commit", "-qm", "contract foundation")
    base = git(root, "rev-parse", "HEAD")
    workspaces = FactoryWorkspaceManager(root)
    adapter = WorkerAdapter(
        workspaces, FileAgentLogStore(tmp_path / "logs"), runner=coder
    )
    auditor = ScriptedProvider("openai", auditor_answers)
    controller = ScriptedProvider("openai", controller_answers)
    control = PackageControl(
        workspaces,
        bound_model(auditor, brand=auditor_brand, bot_profile_id="auditor-bot"),
        bound_model(
            controller, brand=controller_brand, bot_profile_id="controller-bot"
        ),
        security=bound_model(
            ScriptedProvider("openai", security_answers or [APPROVE] * 8),
            brand=security_brand,
            bot_profile_id="security-bot",
        ),
        house_rules=[{"id": "2.1", "rule": "Tests name their criterion"}],
    )
    return root, base, PackageLine(adapter, control, workspaces), auditor, controller


def deliver(pipeline, plan, base, *, task_id="module-rules", fresh=None):
    return pipeline.deliver(
        package(plan, task_id),
        contracts(),
        KRAVSPEC,
        coder=AgentChoice("claude-code", "sk-a"),
        fresh_coder=fresh,
        base_sha=base,
        execution_id="wf-1",
        organization_id="org-1",
        actor_id="pm",
    )


def factory_branches(root: Path) -> list[str]:
    return git(
        root, "branch", "--list", "factory/*", "--format=%(refname:short)"
    ).split()


# --------------------------------------------------------------------- #
# Passing
# --------------------------------------------------------------------- #
def test_a_good_delivery_passes_all_three_controls(tmp_path, plan) -> None:
    root, base, pipeline, auditor, controller = line(
        tmp_path, ScriptedCoder(GOOD_RULES), [APPROVE], [APPROVE]
    )
    outcome = deliver(pipeline, plan, base)

    assert outcome["status"] == "passed", outcome["reason"]
    assert factory_branches(root) == [outcome["branch"]]
    attempt = outcome["attempts"][0]
    assert attempt["control"]["checks"][0] == {
        "name": "tests",
        "status": "passed",
        "exit_code": 0,
    }
    assert [j["role"] for j in outcome["agent_jobs"]] == [
        "coder",
        "code_auditor",
        "security_reviewer",
        "context_controller",
    ]
    assert outcome["agent_jobs"][1]["agent"]["brand"] == "openai"
    assert outcome["measurements"] | {} == {
        "fact_check_passed_first_try": True,
        "level1_passed_first_try": True,
        "security_passed_first_try": True,
        "level2_passed_first_try": True,
        "secrets_found": 0,
        "invented_references": 0,
        "out_of_scope_changes": 0,
        "rework_rounds": 0,
        "discarded_attempts": 0,
        "assumptions": 0,
        "rejected_reviewer_findings": 0,
        "unsupported_verdicts": 0,
    }
    # The controls get a fixed packet: the diff and rules, never the coder's prompt or stream.
    assert "def create" in auditor.prompts[0]
    assert "Work package module-rules" not in auditor.prompts[0]
    assert "result" not in json.dumps(outcome["agent_jobs"][1])
    assert "AC-REG-01-1" in controller.prompts[0]


def test_the_foundation_only_has_to_collect_its_failing_contract_tests(
    tmp_path, plan
) -> None:
    contract_tests = "".join(
        f"def test_{c.lower().replace('-', '_')}():\n    raise NotImplementedError\n\n\n"
        for c in package(plan, "contract-foundation")["criterion_ids"]
    )
    coder = ScriptedCoder(
        {
            "contracts/test_contracts.py": contract_tests,
            "contracts/rules.py": "class RulesApi: ...\n",
        }
    )
    _, base, pipeline, _, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base, task_id="contract-foundation")
    assert outcome["status"] == "passed", outcome["reason"]
    # The contract tests raise until the modules exist; collecting them is enough.
    assert outcome["attempts"][0]["control"]["checks"][0]["status"] == "passed"


# --------------------------------------------------------------------- #
# Fact check and rework
# --------------------------------------------------------------------- #
def test_fact_check_findings_go_back_to_the_coder_and_rework_builds_on_the_delivery(
    tmp_path, plan
) -> None:
    first = {
        **GOOD_RULES,
        # Naming a criterion in the code is not a test of it.
        "src/rules/store.py": "# AC-REG-01-2, AC-REG-02-1\n"
        + GOOD_RULES["src/rules/store.py"],
        "tests/rules/test_store.py": "def test_ac_reg_01_1():\n    assert True\n\n\ndef test_ac_reg_09_9():\n    assert True\n",
    }
    fix = {"tests/rules/test_store.py": GOOD_RULES["tests/rules/test_store.py"]}
    coder = ScriptedCoder(first, fix)
    root, base, pipeline, auditor, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base)

    assert outcome["status"] == "passed"
    assert [a["decision"] for a in outcome["attempts"]] == ["rework", "passed"]
    codes = {f["code"] for f in outcome["attempts"][0]["control"]["findings"]}
    # The test designer's contract tests cover the criteria the coder skipped;
    # naming a criterion in code still does not count (see the unit test below).
    assert codes == {"invented_reference"}
    assert len(auditor.prompts) == 1  # no model is asked while the fact check fails
    # The rework prompt carries the verified findings, and the rework starts from the delivery.
    assert (
        "This is a rework round" in coder.prompts[1]
        and "AC-REG-09-9" in coder.prompts[1]
    )
    assert outcome["attempts"][1]["kind"] == "rework"
    # The rework kept the first delivery's code: it built on it.
    store = git(root, "show", f"{outcome['head_sha']}:src/rules/store.py")
    assert store.startswith("# AC-REG-01-2") and "def create" in store
    # The superseded branch is gone.
    assert factory_branches(root) == [outcome["branch"]]
    m = outcome["measurements"]
    assert (
        m["fact_check_passed_first_try"],
        m["invented_references"],
        m["rework_rounds"],
    ) == (False, 1, 1)


def test_tests_the_factory_runs_must_pass(tmp_path, plan) -> None:
    failing = {
        **GOOD_RULES,
        "src/rules/store.py": "def create(rule):\n    return None\n",
    }
    coder = ScriptedCoder(failing, GOOD_RULES)
    _, base, pipeline, _, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base)
    first = outcome["attempts"][0]["control"]
    assert {f["code"] for f in first["findings"]} == {"tests_failed"}
    assert first["checks"][0]["status"] == "failed"
    assert outcome["status"] == "passed"


# --------------------------------------------------------------------- #
# Level 1 and level 2
# --------------------------------------------------------------------- #
def test_reviewer_findings_must_point_at_real_lines(tmp_path, plan) -> None:
    invented = {
        "verdict": "revise",
        "findings": [finding("src/rules/store.py:99"), finding("src/other.py")],
    }
    _, base, pipeline, _, _ = line(
        tmp_path, ScriptedCoder(GOOD_RULES), [invented], [APPROVE]
    )
    outcome = deliver(pipeline, plan, base)
    assert outcome["status"] == "passed"
    assert outcome["measurements"]["rejected_reviewer_findings"] == 2
    assert outcome["measurements"]["unsupported_verdicts"] == 1


def test_a_level1_finding_sends_the_package_back_and_level2_waits_for_it(
    tmp_path, plan
) -> None:
    real = {"verdict": "revise", "findings": [finding("src/rules/store.py:2")]}
    coder = ScriptedCoder(
        GOOD_RULES, {"src/rules/store.py": GOOD_RULES["src/rules/store.py"] + "\n"}
    )
    _, base, pipeline, _, controller = line(tmp_path, coder, [real, APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base)
    assert [a["control"]["stage"] for a in outcome["attempts"]] == ["level1", "level2"]
    assert len(controller.prompts) == 1  # level 2 only ran after level 1 passed
    assert "src/rules/store.py:2" in coder.prompts[1]
    assert (
        outcome["measurements"]["level1_passed_first_try"],
        outcome["measurements"]["level2_passed_first_try"],
    ) == (False, False)


def test_a_cause_in_the_input_stops_the_line_for_the_change_process(
    tmp_path, plan
) -> None:
    contradiction = {
        "verdict": "revise",
        "findings": [finding("AC-REG-01-1", cause="input")],
    }
    root, base, pipeline, _, _ = line(
        tmp_path, ScriptedCoder(GOOD_RULES), [APPROVE], [contradiction]
    )
    outcome = deliver(pipeline, plan, base)
    assert outcome["status"] == "change_input"
    assert len(outcome["attempts"]) == 1 and outcome["branch"] is None
    assert factory_branches(root) == []


def test_two_rework_rounds_then_a_fresh_agent_then_the_human(tmp_path, plan) -> None:
    blocking = {"verdict": "revise", "findings": [finding("src/rules/store.py:1")]}
    touch = {"src/rules/store.py": GOOD_RULES["src/rules/store.py"] + "# again\n"}
    coder = ScriptedCoder(GOOD_RULES, touch, touch, GOOD_RULES)
    root, base, pipeline, _, _ = line(tmp_path, coder, [blocking] * 4, [])
    outcome = deliver(pipeline, plan, base, fresh=AgentChoice("claude-code", "sk-b"))

    assert outcome["status"] == "escalated"
    assert [(a["kind"], a["decision"]) for a in outcome["attempts"]] == [
        ("initial", "rework"),
        ("rework", "rework"),
        ("rework", "regenerate"),
        ("regenerate", "escalate"),
    ]
    assert (
        "This is a rework round" not in coder.prompts[3]
    )  # the fresh agent starts clean
    assert factory_branches(root) == []
    assert (
        outcome["measurements"]["rework_rounds"],
        outcome["measurements"]["discarded_attempts"],
    ) == (2, 1)


def test_a_crashed_worker_is_rebuilt_by_the_fresh_agent(tmp_path, plan) -> None:
    coder = ScriptedCoder(None, GOOD_RULES)
    _, base, pipeline, _, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base, fresh=AgentChoice("codex", "sk-o"))
    assert [a["decision"] for a in outcome["attempts"]] == ["regenerate", "waiting"]
    # The fresh agent is from OpenAI, like the controls: the control waits, it never falls back.
    assert outcome["status"] == "waiting"
    assert "different" in outcome["reason"] or "producer" in outcome["reason"]
    assert outcome["branch"] is not None


# --------------------------------------------------------------------- #
# Independence
# --------------------------------------------------------------------- #
def test_controls_from_the_coders_producer_wait_without_calling_a_model(
    tmp_path, plan
) -> None:
    root, base, pipeline, auditor, controller = line(
        tmp_path,
        ScriptedCoder(GOOD_RULES),
        [APPROVE],
        [APPROVE],
        controller_brand="anthropic",
    )
    outcome = deliver(pipeline, plan, base)
    assert outcome["status"] == "waiting"
    assert auditor.prompts == [] and controller.prompts == []
    assert factory_branches(root) == [outcome["branch"]]  # kept until a control can run


# --------------------------------------------------------------------- #
# Units
# --------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("control", "worker_failed", "generation", "rounds", "expected"),
    [
        (None, True, 1, 0, "regenerate"),
        (None, True, 2, 0, "escalate"),
        ({"status": "passed"}, False, 1, 0, "passed"),
        ({"status": "waiting"}, False, 1, 0, "waiting"),
        ({"status": "failed", "cause": "input"}, False, 1, 0, "change_input"),
        ({"status": "failed", "cause": "code"}, False, 1, 1, "rework"),
        ({"status": "failed", "cause": "code"}, False, 1, 2, "regenerate"),
        ({"status": "failed", "cause": "code"}, False, 2, 0, "escalate"),
    ],
)
def test_triage(control, worker_failed, generation, rounds, expected) -> None:
    assert (
        triage(
            control,
            worker_failed=worker_failed,
            generation=generation,
            rework_rounds=rounds,
        )
        == expected
    )


def test_verify_findings() -> None:
    files = {"a.py": "x = 1\ny = 2\n"}
    verified, rejected = verify_findings(
        {
            "findings": [
                finding("a.py:2"),
                finding("a.py:3"),
                finding("a.py"),
                finding("AC-1"),
                finding("b.py"),
            ]
        },
        files=files,
        other_targets={"AC-1"},
        requirement_ids={"REG-01"},
    )
    assert [f["target"] for f in verified] == ["a.py:2", "a.py", "AC-1"]
    assert [f["target"] for f in rejected] == ["a.py:3", "b.py"]


def test_control_configuration_needs_both_profiles(tmp_path, monkeypatch) -> None:
    root, _ = repository(tmp_path)
    workspaces = FactoryWorkspaceManager(root)
    monkeypatch.delenv("DOR_CODE_AUDITOR_BOT_PROFILE", raising=False)
    monkeypatch.delenv("DOR_CONTEXT_CONTROLLER_BOT_PROFILE", raising=False)
    assert default_package_control("org-1", workspaces) is None
    monkeypatch.setenv("DOR_CODE_AUDITOR_BOT_PROFILE", "auditor")
    with pytest.raises(PackageControlConfigurationError):
        default_package_control("org-1", workspaces)


# --------------------------------------------------------------------- #
# Decision 43: security review, secret scan, the test designer's tests
# --------------------------------------------------------------------- #
def test_a_security_finding_sends_the_package_back_before_level2(
    tmp_path, plan
) -> None:
    risk = {"verdict": "revise", "findings": [finding("src/rules/store.py:1")]}
    coder = ScriptedCoder(
        GOOD_RULES, {"src/rules/store.py": GOOD_RULES["src/rules/store.py"] + "\n"}
    )
    _, base, pipeline, _, controller = line(
        tmp_path, coder, [APPROVE] * 2, [APPROVE], security_answers=[risk, APPROVE]
    )
    outcome = deliver(pipeline, plan, base)
    assert [a["control"]["stage"] for a in outcome["attempts"]] == [
        "security",
        "level2",
    ]
    assert len(controller.prompts) == 1
    assert outcome["measurements"]["security_passed_first_try"] is False
    assert outcome["status"] == "passed"


def test_the_secret_scan_stops_a_delivery_with_a_key(tmp_path, plan) -> None:
    leaky = {
        **GOOD_RULES,
        "src/rules/config.py": 'API_KEY = "sk-ant-abcdefghijklmnopqrstuvwxyz123456"\n',
    }
    coder = ScriptedCoder(leaky, {"src/rules/config.py": "API_KEY = None\n"})
    _, base, pipeline, auditor, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base)
    first = outcome["attempts"][0]["control"]
    assert {f["code"] for f in first["findings"]} == {"secret_in_delivery"}
    assert first["findings"][0]["target"] == "src/rules/config.py:1"
    assert (
        len(auditor.prompts) == 1
    )  # no model saw the key; the second delivery is clean
    assert outcome["measurements"]["secrets_found"] == 1
    assert outcome["status"] == "passed"


def test_a_module_needs_the_test_designers_acceptance_tests(tmp_path, plan) -> None:
    coder = ScriptedCoder(*[GOOD_RULES] * 4)
    root, base, pipeline, _, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    git(root, "rm", "-q", "contracts/test_rules_contract.py")
    git(root, "commit", "-qm", "no acceptance tests")
    base = git(root, "rev-parse", "HEAD")
    outcome = deliver(pipeline, plan, base)
    codes = {f["code"] for f in outcome["attempts"][0]["control"]["findings"]}
    assert codes == {"criterion_without_acceptance_test"}


def test_naming_a_criterion_in_code_is_not_a_test(tmp_path, plan) -> None:
    contract_tests = "def test_ac_reg_01_1():\n    pass\n"
    named = "# AC-REG-01-2 AC-REG-02-1 AC-REG-03-1\nclass RulesApi: ...\n"
    coder = ScriptedCoder(
        *[{"contracts/test_x.py": contract_tests, "contracts/api.py": named}] * 4
    )
    _, base, pipeline, _, _ = line(tmp_path, coder, [APPROVE], [APPROVE])
    outcome = deliver(pipeline, plan, base, task_id="contract-foundation")
    missing = {
        f["target"]
        for f in outcome["attempts"][0]["control"]["findings"]
        if f["code"] == "criterion_without_test"
    }
    assert missing == {"AC-REG-01-2", "AC-REG-02-1", "AC-REG-03-1"}


def test_a_coder_from_the_test_designers_producer_never_starts(tmp_path, plan) -> None:
    coder = ScriptedCoder(GOOD_RULES)
    _, base, pipeline, auditor, _ = line(
        tmp_path,
        coder,
        [APPROVE],
        [APPROVE],
        auditor_brand="google",
        controller_brand="google",
        security_brand="google",
    )
    outcome = pipeline.deliver(
        package(plan, "module-rules"),
        contracts(),
        KRAVSPEC,
        coder=AgentChoice("claude-code", "sk-a"),
        base_sha=base,
        execution_id="wf-1",
        organization_id="org-1",
        actor_id="pm",
        test_designer={"brand": "anthropic", "session_id": "td-1"},
    )
    assert outcome["status"] == "waiting" and "producer" in outcome["reason"]
    assert coder.prompts == [] and auditor.prompts == []
    outcome = pipeline.deliver(
        package(plan, "module-rules"),
        contracts(),
        KRAVSPEC,
        coder=AgentChoice("claude-code", "sk-a"),
        base_sha=base,
        execution_id="wf-1",
        organization_id="org-1",
        actor_id="pm",
        test_designer={"brand": "openai", "session_id": "td-1"},
    )
    assert outcome["status"] == "passed", outcome["reason"]


def test_without_a_security_reviewer_nothing_passes(tmp_path, plan) -> None:
    root, _ = repository(tmp_path)
    workspaces = FactoryWorkspaceManager(root)
    control = PackageControl(
        workspaces,
        bound_model(
            ScriptedProvider("openai", [APPROVE]), brand="openai", bot_profile_id="a"
        ),
        bound_model(
            ScriptedProvider("openai", [APPROVE]), brand="openai", bot_profile_id="c"
        ),
    )
    assert "security reviewer" in control.independence_problem(
        "module-rules", "coder", "anthropic", "s", "k"
    )


def test_control_configuration_needs_all_three_profiles(tmp_path, monkeypatch) -> None:
    root, _ = repository(tmp_path)
    workspaces = FactoryWorkspaceManager(root)
    for name in (
        "DOR_CODE_AUDITOR_BOT_PROFILE",
        "DOR_CONTEXT_CONTROLLER_BOT_PROFILE",
        "DOR_SECURITY_REVIEWER_BOT_PROFILE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DOR_CODE_AUDITOR_BOT_PROFILE", "a")
    monkeypatch.setenv("DOR_CONTEXT_CONTROLLER_BOT_PROFILE", "c")
    with pytest.raises(PackageControlConfigurationError, match="SECURITY"):
        default_package_control("org-1", workspaces)


def test_the_control_itself_rechecks_the_test_designers_producer(tmp_path) -> None:
    root, _ = repository(tmp_path)
    control = PackageControl(
        FactoryWorkspaceManager(root),
        bound_model(ScriptedProvider("openai", []), brand="openai", bot_profile_id="a"),
        bound_model(ScriptedProvider("openai", []), brand="openai", bot_profile_id="c"),
        security=bound_model(
            ScriptedProvider("openai", []), brand="openai", bot_profile_id="s"
        ),
    )
    same = {"brand": "anthropic", "session_id": "td"}
    assert "producer" in control.independence_problem(
        "module-rules", "coder", "anthropic", "s", "k", test_designer=same
    )
    # The test designer's own foundation is not judged against itself.
    assert (
        control.independence_problem(
            "contract-foundation",
            "test_designer",
            "anthropic",
            "s",
            "k",
            test_designer=same,
        )
        is None
    )
