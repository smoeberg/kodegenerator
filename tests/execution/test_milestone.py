"""Completion plan step 8: the milestone branch.

A real git repository, the real package line (worker adapter, fact check
with real test runs, scripted level 1 and level 2) and the real full suite.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from execution.milestone import (
    FileMilestoneStore,
    MilestoneError,
    MilestoneRunner,
    restore_known_good,
)
from execution.package_control import AgentChoice, PackageControl, PackageLine
from execution.role_dialogue import fingerprint
from execution.task_compiler import compile_work_plan
from execution.worker_adapter import AgentRun, WorkerAdapter
from services.agent_log_store import FileAgentLogStore
from services.bot_llm_runtime import bound_model
from services.factory_workspace import FactoryWorkspaceManager
from tests.execution.test_contract_council import KRAVSPEC, ScriptedProvider, contracts

APPROVE = {"verdict": "approve", "findings": []}
READY = {
    "recommendation": "ready",
    "release_notes": "Delivers REG-01, REG-02 and REG-03 through module-rules and module-metrics.",
    "reasons": [],
    "risks": [],
}
REQUIREMENTS = "d" * 64

FOUNDATION = {
    "contracts/rules.py": "class RulesApi:\n    pass\n",
    "contracts/test_rules_contract.py": (
        "def test_ac_reg_01_1_contract():\n    from src.rules.store import create\n    assert create({'id': 'x'})['id'] == 'x'\n\n\n"
        "def test_ac_reg_01_2_contract():\n    from src.rules.store import create\n\n\n"
        "def test_ac_reg_02_1_contract():\n    from src.rules.store import create\n"
    ),
    "contracts/test_metrics_contract.py": (
        "def test_ac_reg_03_1_contract():\n    from src.metrics.record import record\n    assert record(1) == 1\n"
    ),
}
RULES = {
    "src/rules/store.py": "def create(rule):\n    return {'id': rule['id']}\n",
    "tests/rules/test_store.py": (
        "from src.rules.store import create\n\n\n"
        "def test_ac_reg_01_1():\n    assert create({'id': 'r'}) == {'id': 'r'}\n\n\n"
        "def test_ac_reg_01_2():\n    assert True\n\n\n"
        "def test_ac_reg_02_1():\n    assert True\n"
    ),
}
METRICS = {
    "src/metrics/record.py": "def record(value):\n    return value\n",
    "tests/metrics/test_record.py": (
        "from src.metrics.record import record\n\n\ndef test_ac_reg_03_1():\n    assert record(2) == 2\n"
    ),
}


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=True
    ).stdout.strip()


def commit(root: Path, files: dict[str, str], message: str) -> str:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    git(root, "add", ".")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


class DispatchCoder:
    """Scripted coding agent: deliveries per work package, optionally in lockstep."""

    def __init__(
        self, deliveries: dict[str, list[dict[str, str]]], *, barrier: int = 0
    ) -> None:
        self.deliveries = {k: list(v) for k, v in deliveries.items()}
        self.calls: list[str] = []
        self._barrier = threading.Barrier(barrier) if barrier else None

    def __call__(self, command, prompt: str, cwd: Path, **_: Any) -> AgentRun:
        task = prompt.split("\n", 1)[0].split()[3]
        self.calls.append(task)
        if self._barrier is not None:
            try:
                self._barrier.wait(timeout=10)
            except threading.BrokenBarrierError:
                pass
        for name, text in self.deliveries[task].pop(0).items():
            (cwd / name).parent.mkdir(parents=True, exist_ok=True)
            (cwd / name).write_text(text)
        return AgentRun(0, [], "", 0.1, session_id=f"{task}-{len(self.calls)}")


@pytest.fixture
def plan():
    return compile_work_plan(
        contracts(),
        workflow_id="wf-1",
        organization_id="org-1",
        contract_fingerprint=fingerprint(contracts()),
        architecture_fingerprint="a" * 64,
        requirements_fingerprint=REQUIREMENTS,
    )


@pytest.fixture
def factory(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.test")
    commit(
        root,
        {
            "README.md": "base\n",
            "tests/test_base.py": "def test_base():\n    assert True\n",
        },
        "base",
    )

    def build(
        coder: DispatchCoder,
        *,
        whole_brand="google",
        controller_brand="google",
        answers=40,
        governance_brand="google",
        architect_answers=None,
        owner_answers=None,
        release_answers=None,
        governance=True,
    ):
        workspaces = FactoryWorkspaceManager(root)
        adapter = WorkerAdapter(
            workspaces, FileAgentLogStore(tmp_path / "logs"), runner=coder
        )
        control = PackageControl(
            workspaces,
            bound_model(
                ScriptedProvider("google", [APPROVE] * answers),
                brand="google",
                bot_profile_id="auditor",
            ),
            bound_model(
                ScriptedProvider("openai", [APPROVE] * answers),
                brand=controller_brand,
                bot_profile_id="controller",
            ),
            security=bound_model(
                ScriptedProvider("google", [APPROVE] * answers),
                brand="google",
                bot_profile_id="security",
            ),
            house_rules=[],
        )
        whole = ScriptedProvider("openai", [APPROVE] * 4)
        providers = {
            "system_architect": ScriptedProvider(
                "google", architect_answers or [APPROVE] * 2
            ),
            "product_owner": ScriptedProvider("google", owner_answers or [APPROVE] * 2),
            "release_manager": ScriptedProvider(
                "google", release_answers or [READY] * 2
            ),
        }
        board = (
            {
                role: bound_model(provider, brand=governance_brand, bot_profile_id=role)
                for role, provider in providers.items()
            }
            if governance
            else None
        )
        runner = MilestoneRunner(
            workspaces,
            PackageLine(adapter, control, workspaces),
            control,
            FileMilestoneStore(tmp_path / "milestones"),
            whole_controller=bound_model(
                whole, brand=whole_brand, bot_profile_id="whole"
            ),
            max_parallel=2,
            governance=board,
        )
        runner.governance_providers = providers
        return runner, control, whole

    return root, build


def run_sprint(runner, plan, sprint):
    return runner.run_sprint(
        "M1",
        sprint,
        plan,
        contracts(),
        KRAVSPEC,
        coder=CODERS,
        fresh_coder=None,
        execution_id="wf-1",
        organization_id="org-1",
        actor_id="pm",
    )


def CODERS(package):
    """The test designer (Anthropic) writes the foundation; coders (OpenAI) the modules."""
    if package["task_type"] == "contract_foundation":
        return AgentChoice("claude-code", "sk-a")
    return AgentChoice("codex", "sk-o")


def start(runner, plan, **kwargs):
    return runner.start(
        plan, requirements_fingerprint=REQUIREMENTS, actor="pm", **kwargs
    )


def top(root: Path) -> str:
    return git(root, "rev-parse", "milestone/M1")


def foundation_sprint(runner, plan) -> dict:
    runner.start_sprint("M1", 1, actor="pm")
    state = run_sprint(runner, plan, 1)
    return (
        runner.review_sprint("M1", 1, "approved", reviewer="pm")
        if not state["sprints"][-1]["exceptions"]
        else state
    )


# --------------------------------------------------------------------- #
# The whole milestone
# --------------------------------------------------------------------- #
def test_a_milestone_from_main_to_known_good(factory, plan, tmp_path) -> None:
    root, build = factory
    coder = DispatchCoder(
        {
            "contract-foundation": [FOUNDATION],
            "module-rules": [RULES],
            "module-metrics": [METRICS],
        },
        barrier=2,
    )
    runner, _, whole = build(coder)
    main_at_start = git(root, "rev-parse", "main")
    start(runner, plan)
    assert top(root) == main_at_start

    state = foundation_sprint(runner, plan)
    foundation = state["sprints"][0]["packages"]["contract-foundation"]
    assert foundation["status"] == "merged" and not foundation["rechecked"]
    assert foundation["binding"] == {
        "start_sha": main_at_start,
        "requirements_fingerprint": REQUIREMENTS,
        "contract_fingerprint": fingerprint(contracts()),
    }

    # Sprint 2: contract tests for unbuilt modules are left out of the start suite.
    state = runner.start_sprint("M1", 2, actor="pm")
    sprint2 = state["sprints"][-1]
    assert sprint2["status"] == "started", (
        sprint2.get("reason"),
        (sprint2.get("suite") or {}).get("output"),
    )
    assert sorted(sprint2["suite"]["ignored"]) == [
        "contracts/test_metrics_contract.py",
        "contracts/test_rules_contract.py",
    ]
    assert (
        git(root, "rev-parse", "refs/tags/dor-sprint/M1/2-run1-start")
        == sprint2["start_sha"]
    )

    state = run_sprint(runner, plan, 2)
    results = state["sprints"][-1]["packages"]
    assert {t: r["status"] for t, r in results.items()} == {
        "module-metrics": "merged",
        "module-rules": "merged",
    }
    # Both started from the same top; the one merged second was rebased and controlled again.
    assert sorted(r["rechecked"] for r in results.values()) == [False, True]
    rechecked = next(r for r in results.values() if r["rechecked"])
    assert rechecked["recheck"]["status"] == "passed"
    assert [j["role"] for j in rechecked["agent_jobs"]][-3:] == [
        "code_auditor",
        "security_reviewer",
        "context_controller",
    ]
    # The foundation was the test designer's; the modules were coded by another producer.
    assert (
        state["packages"]["contract-foundation"]["delivered_by"]["role"]
        == "test_designer"
    )
    assert {state["packages"][t]["delivered_by"]["brand"] for t in results} == {
        "openai"
    }
    assert git(root, "branch", "--list", "factory/*") == ""
    for path in ("src/rules/store.py", "src/metrics/record.py", "contracts/rules.py"):
        assert git(root, "cat-file", "-t", f"milestone/M1:{path}") == "blob"

    runner.review_sprint("M1", 2, "approved", reviewer="pm")
    state = runner.finish(
        "M1", contracts(), KRAVSPEC, organization_id="org-1", actor_id="pm"
    )
    assert state["status"] == "awaiting_approval"
    assert state["milestone_review"]["suite"]["ignored"] == []
    assert "src/metrics/record.py" in whole.prompts[0]

    state = runner.approve("M1", approver="pm")
    head = state["approved_head_sha"]
    # The one PR to main (merged here by hand).
    git(root, "merge", "-q", "--no-ff", "-m", "Merge milestone M1", "milestone/M1")
    merged = git(root, "rev-parse", "main")
    state = runner.mark_merged(
        "M1", main_sha=merged, actor="pm", backup_dir=tmp_path / "backup"
    )

    assert state["status"] == "merged"
    assert git(root, "rev-parse", "known-good/M1") == merged
    assert git(root, "branch", "--list", "milestone/*") == ""
    bundle = Path(state["backup"]["bundle"])
    assert bundle.exists()
    subprocess.run(
        ["git", "bundle", "verify", str(bundle)],
        cwd=root,
        check=True,
        capture_output=True,
    )
    evidence = json.loads(
        (tmp_path / "backup" / "M1" / "M1-release-evidence.json").read_text()
    )
    assert (evidence["approved_head_sha"], evidence["main_sha"]) == (head, merged)
    assert restore_known_good(runner._workspaces, "M1", branch="rollback/m1") == merged


# --------------------------------------------------------------------- #
# Sprint start
# --------------------------------------------------------------------- #
def test_sprint_start_rebases_onto_the_newest_main(factory, plan) -> None:
    root, build = factory
    runner, _, _ = build(DispatchCoder({"contract-foundation": [FOUNDATION]}))
    start(runner, plan)
    foundation_sprint(runner, plan)
    moved = commit(root, {"docs/note.md": "from someone else\n"}, "main moves")
    state = runner.start_sprint("M1", 2, actor="pm")
    assert git(root, "merge-base", "--is-ancestor", moved, top(root)) == ""
    assert state["sprints"][-1]["main_sha"] == moved


def test_a_conflicting_or_red_main_is_an_exception_before_the_sprint(
    factory, plan
) -> None:
    root, build = factory
    runner, _, _ = build(DispatchCoder({"contract-foundation": [FOUNDATION]}))
    start(runner, plan)
    foundation_sprint(runner, plan)
    before = top(root)
    commit(
        root,
        {"contracts/rules.py": "class Other:\n    pass\n"},
        "conflicting change on main",
    )
    state = runner.start_sprint("M1", 2, actor="pm")
    assert (
        state["sprints"][-1]["status"] == "exception"
        and "conflicts" in state["sprints"][-1]["reason"]
    )
    assert top(root) == before

    git(root, "reset", "-q", "--hard", "HEAD~1")
    commit(
        root, {"tests/test_red.py": "def test_red():\n    assert False\n"}, "red main"
    )
    state = runner.start_sprint("M1", 2, actor="pm")
    assert "full suite fails" in state["sprints"][-1]["reason"]
    assert top(root) == before


def test_daily_review_and_dependencies_gate_the_next_sprint(factory, plan) -> None:
    _, build = factory
    runner, _, _ = build(DispatchCoder({"contract-foundation": [FOUNDATION]}))
    start(runner, plan)
    with pytest.raises(MilestoneError, match="unmerged packages"):
        runner.start_sprint("M1", 2, actor="pm")
    runner.start_sprint("M1", 1, actor="pm")
    run_sprint(runner, plan, 1)
    with pytest.raises(MilestoneError, match="awaits the project manager"):
        runner.start_sprint("M1", 2, actor="pm")


def test_exception_mode_continues_while_the_controls_pass(factory, plan) -> None:
    _, build = factory
    runner, _, _ = build(DispatchCoder({"contract-foundation": [FOUNDATION]}))
    start(runner, plan, review_mode="exceptions")
    runner.start_sprint("M1", 1, actor="pm")
    run_sprint(runner, plan, 1)
    assert (
        runner.start_sprint("M1", 2, actor="pm")["sprints"][-1]["status"] == "started"
    )


# --------------------------------------------------------------------- #
# Discard, recheck failure, input change
# --------------------------------------------------------------------- #
def test_a_discarded_sprint_resets_to_its_start_mark(factory, plan) -> None:
    root, build = factory
    runner, _, _ = build(
        DispatchCoder({"contract-foundation": [FOUNDATION, FOUNDATION]})
    )
    start(runner, plan)
    started = runner.start_sprint("M1", 1, actor="pm")["sprints"][-1]["start_sha"]
    run_sprint(runner, plan, 1)
    assert top(root) != started
    state = runner.review_sprint(
        "M1", 1, "discarded", reviewer="pm", note="wrong approach"
    )
    assert top(root) == started
    assert state["packages"]["contract-foundation"]["status"] == "pending"
    again = runner.start_sprint("M1", 1, actor="pm")["sprints"][-1]
    assert again["run"] == 2
    assert (
        run_sprint(runner, plan, 1)["packages"]["contract-foundation"]["status"]
        == "merged"
    )


def test_a_failed_recheck_rebuilds_the_package_from_the_new_top(factory, plan) -> None:
    _, build = factory
    coder = DispatchCoder(
        {
            "contract-foundation": [FOUNDATION],
            "module-rules": [RULES, RULES],
            "module-metrics": [METRICS, METRICS],
        },
        barrier=2,
    )
    runner, control, _ = build(coder)
    original = control.check
    failed = []

    def check(*args, **kwargs):
        if ":recheck:" in kwargs["run_key"] and not failed:
            failed.append(kwargs["run_key"])
            return {
                "status": "failed",
                "stage": "level2",
                "cause": "code",
                "findings": [],
                "agent_jobs": [],
            }
        return original(*args, **kwargs)

    control.check = check
    start(runner, plan)
    foundation_sprint(runner, plan)
    runner.start_sprint("M1", 2, actor="pm")
    results = run_sprint(runner, plan, 2)["sprints"][-1]["packages"]
    assert {r["status"] for r in results.values()} == {"merged"}
    rebuilt = next(r for r in results.values() if r["redelivered"])
    assert (
        rebuilt["earlier"]["status"] == "rebuild"
        and "recheck" in rebuilt["earlier"]["reason"]
    )
    assert len(coder.calls) == 4  # foundation, two modules, one rebuild


def test_an_input_change_takes_effect_at_the_next_sprint_start(factory, plan) -> None:
    _, build = factory
    runner, _, _ = build(DispatchCoder({"contract-foundation": [FOUNDATION]}))
    start(runner, plan)
    foundation_sprint(runner, plan)
    state = runner.change_input("M1", actor="pm", requirements_fingerprint="e" * 64)
    assert (
        state["requirements_fingerprint"] == REQUIREMENTS
    )  # frozen until the sprint starts
    sprint = runner.start_sprint("M1", 2, actor="pm")["sprints"][-1]
    assert sprint["frozen"]["requirements_fingerprint"] == "e" * 64
    assert sprint["bound_to_old_input"] == ["contract-foundation"]


# --------------------------------------------------------------------- #
# Milestone gates
# --------------------------------------------------------------------- #
def test_the_milestone_cannot_be_finished_or_approved_early(
    factory, plan, tmp_path
) -> None:
    root, build = factory
    runner, _, _ = build(DispatchCoder({"contract-foundation": [FOUNDATION]}))
    start(runner, plan)
    with pytest.raises(MilestoneError, match="not merged"):
        runner.finish(
            "M1", contracts(), KRAVSPEC, organization_id="org-1", actor_id="pm"
        )
    with pytest.raises(MilestoneError, match="not awaiting approval"):
        runner.approve("M1", approver="pm")
    with pytest.raises(MilestoneError, match="only an approved"):
        runner.mark_merged(
            "M1",
            main_sha=git(root, "rev-parse", "main"),
            actor="pm",
            backup_dir=tmp_path,
        )
    with pytest.raises(MilestoneError, match="contracts are not"):
        runner.start_sprint("M1", 1, actor="pm")
        runner.run_sprint(
            "M1",
            1,
            plan,
            {"modules": []},
            KRAVSPEC,
            coder=AgentChoice("claude-code", "k"),
            fresh_coder=None,
            execution_id="wf-1",
            organization_id="org-1",
            actor_id="pm",
        )


def test_whole_level2_waits_for_a_controller_independent_of_every_coder(
    factory, plan
) -> None:
    _, build = factory
    coder = DispatchCoder(
        {
            "contract-foundation": [FOUNDATION],
            "module-rules": [RULES],
            "module-metrics": [METRICS],
        }
    )
    runner, _, whole = build(coder, whole_brand="anthropic")
    start(runner, plan)
    foundation_sprint(runner, plan)
    runner.start_sprint("M1", 2, actor="pm")
    run_sprint(runner, plan, 2)
    runner.review_sprint("M1", 2, "approved", reviewer="pm")
    state = runner.finish(
        "M1", contracts(), KRAVSPEC, organization_id="org-1", actor_id="pm"
    )
    assert state["status"] == "running"
    assert state["milestone_review"]["status"] == "waiting"
    assert whole.prompts == []


# --------------------------------------------------------------------- #
# Decision 40: governance on the milestone
# --------------------------------------------------------------------- #
def finished(build, plan, **kwargs):
    coder = DispatchCoder(
        {
            "contract-foundation": [FOUNDATION],
            "module-rules": [RULES],
            "module-metrics": [METRICS],
        }
    )
    runner, _, _ = build(coder, **kwargs)
    start(runner, plan)
    foundation_sprint(runner, plan)
    runner.start_sprint("M1", 2, actor="pm")
    run_sprint(runner, plan, 2)
    runner.review_sprint("M1", 2, "approved", reviewer="pm")
    state = runner.finish(
        "M1",
        contracts(),
        KRAVSPEC,
        organization_id="org-1",
        actor_id="pm",
        architecture={"modules": [{"module_id": "rules"}, {"module_id": "metrics"}]},
    )
    return runner, state


def test_the_board_gets_the_architect_the_owner_and_the_release_manager(
    factory, plan
) -> None:
    _, build = factory
    runner, state = finished(build, plan)
    review = state["milestone_review"]
    assert state["status"] == "awaiting_approval", review.get("reason")
    assert list(review["stages"]) == [
        "level2",
        "architecture",
        "mandate",
        "checklist",
        "release",
    ]
    assert all(item["holds"] for item in review["stages"]["checklist"]["items"])
    assert review["stages"]["release"]["recommendation"] == "ready"
    roles = [j["role"] for j in review["agent_jobs"]]
    assert roles == [
        "context_controller",
        "system_architect",
        "product_owner",
        "release_manager",
    ]
    # The owner sees which criteria the factory's tests cover; the architect the architecture.
    owner = runner.governance_providers["product_owner"].prompts[0]
    assert "criteria_tested" in owner and "contracts/test_rules_contract.py" in owner
    assert (
        "approved_architecture"
        in runner.governance_providers["system_architect"].prompts[0]
    )
    stats = review["statistics"]
    assert stats["packages"]["merged"] == 3
    assert {(r["role"], r["brand"]) for r in stats["by_role_and_producer"]} >= {
        ("test_designer", "anthropic"),
        ("coder", "openai"),
        ("security_reviewer", "google"),
        ("release_manager", "google"),
    }
    assert any(
        ref.startswith("product_owner/check_mandate@v1+")
        for ref in stats["by_prompt_version"]
    )


def test_without_the_governance_roles_the_milestone_waits(factory, plan) -> None:
    _, build = factory
    _, state = finished(build, plan, governance=False)
    assert state["status"] == "running"
    assert state["milestone_review"]["status"] == "waiting"
    assert "system_architect" in state["milestone_review"]["reason"]


def test_governance_from_a_builders_producer_waits(factory, plan) -> None:
    _, build = factory
    runner, state = finished(build, plan, governance_brand="openai")
    assert state["milestone_review"]["status"] == "waiting"
    assert "different producer" in state["milestone_review"]["reason"]
    assert runner.governance_providers["system_architect"].prompts == []


def test_a_mandate_finding_in_the_input_stops_the_milestone(factory, plan) -> None:
    _, build = factory
    contradiction = {
        "verdict": "revise",
        "findings": [
            {
                "id": "PO-1",
                "severity": "blocking",
                "target": "REG-02",
                "issue": "contradicts REG-01",
                "requirement_ids": ["REG-02"],
                "cause": "input",
            }
        ],
    }
    runner, state = finished(build, plan, owner_answers=[contradiction])
    review = state["milestone_review"]
    assert (state["status"], review["status"]) == ("running", "failed")
    assert review["stages"]["mandate"]["cause"] == "input"
    assert "release" not in review["stages"]
    assert runner.governance_providers["release_manager"].prompts == []


def test_release_notes_that_invent_ids_are_not_accepted(factory, plan) -> None:
    _, build = factory
    invented = {
        **READY,
        "release_notes": "Delivers REG-01 and REG-99 through module-ghost.",
    }
    _, state = finished(build, plan, release_answers=[invented])
    release = state["milestone_review"]["stages"]["release"]
    assert (
        release["status"] == "failed"
        and "REG-99" in release["reason"]
        and "module-ghost" in release["reason"]
    )
    assert state["status"] == "running"
