"""Completion plan step 6: the worker adapter.

Ready-made coding agents run headless in an isolated worktree on one work
package. DOR commits and attests what is left behind; the agent cannot
push; every run writes an immutable agent log. Fake ``claude`` and ``codex``
executables stand in for the real CLIs.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

from domain.prompt_registry import PromptRegistry
from execution.task_compiler import compile_work_plan
from execution.worker_adapter import (
    AGENT_COMMANDS,
    WorkerAdapter,
    active_house_rules,
    build_task,
    main,
    parse_stream,
    scrubbed_environment,
)
from services.agent_log_store import AgentLogError, FileAgentLogStore
from services.factory_workspace import FactoryWorkspaceManager
from tests.execution.test_contract_council import KRAVSPEC, contracts


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=True
    ).stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.test")
    (root / "README.md").write_text("base\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return root, git(root, "rev-parse", "HEAD")


def fake_agent(bin_dir: Path, name: str, body: str) -> None:
    """A fake CLI: runs ``body`` (Python) in the worktree, prints a stream."""
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / name
    script.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys, time, pathlib\n"
        + textwrap.dedent(body)
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


CLAUDE_WRITES_RULES = """
print(json.dumps({"type": "system", "session_id": "claude-session-1"}))
pathlib.Path("src/rules").mkdir(parents=True, exist_ok=True)
pathlib.Path("src/rules/store.py").write_text("def create():\\n    return 1\\n")
pathlib.Path("tests/rules").mkdir(parents=True, exist_ok=True)
pathlib.Path("tests/rules/test_store.py").write_text("def test_ac_reg_01_1():\\n    assert True\\n")
print(json.dumps({"type": "result", "session_id": "claude-session-1", "usage": {"input_tokens": 1200, "output_tokens": 300}, "total_cost_usd": 0.04}))
"""


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


def package(plan, task_id: str):
    return next(p for p in plan["packages"] if p["logical_task_id"] == task_id)


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root, base = repository(tmp_path)
    bin_dir = tmp_path / "bin"
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    store = FileAgentLogStore(tmp_path / "logs")
    adapter = WorkerAdapter(FactoryWorkspaceManager(root), store)
    return root, base, bin_dir, store, adapter


def run(adapter, plan, base, task_id="module-rules", agent="claude-code", **kwargs):
    return adapter.run(
        package(plan, task_id),
        contracts(),
        KRAVSPEC,
        agent=agent,
        base_sha=base,
        execution_id="wf-1",
        api_key="sk-test",
        **kwargs,
    )


# --------------------------------------------------------------------- #
# Task format
# --------------------------------------------------------------------- #
def test_active_house_rules_exclude_rules_on_trial() -> None:
    ids = {rule["id"] for rule in active_house_rules()}
    assert "1.1" in ids and "8.2" in ids
    assert "1.3" not in ids and "8.1" not in ids


def test_module_task_carries_only_its_own_contract_and_criteria(plan) -> None:
    prompt, packet = build_task(
        package(plan, "module-rules"), contracts(), KRAVSPEC, house_rules=[]
    )
    assert [c["module_id"] for c in packet["contracts"]] == ["rules"]
    assert {c["id"] for c in packet["acceptance_criteria"]} == {
        "AC-REG-01-1",
        "AC-REG-01-2",
        "AC-REG-02-1",
    }
    assert {r["id"] for r in packet["requirements"]} == {"REG-01", "REG-02"}
    assert "Change files only under: src/rules, tests/rules" in prompt
    assert "Do not change contracts/" in prompt
    assert packet["prompt_versions"] == [
        PromptRegistry.load().active("coder", "implement_module").ref
    ]


def test_foundation_task_carries_every_contract(plan) -> None:
    prompt, packet = build_task(
        package(plan, "contract-foundation"), contracts(), KRAVSPEC, house_rules=[]
    )
    assert {c["module_id"] for c in packet["contracts"]} == {"rules", "metrics"}
    assert "Do not implement modules" in prompt


# --------------------------------------------------------------------- #
# Stream parsing and environment
# --------------------------------------------------------------------- #
def test_stream_parsing_for_both_agents() -> None:
    claude = [
        json.dumps({"type": "system", "session_id": "s1"}),
        "not json",
        json.dumps(
            {
                "type": "result",
                "usage": {"input_tokens": 5, "output_tokens": 2},
                "total_cost_usd": 0.01,
            }
        ),
    ]
    assert parse_stream("claude-code", claude) == (
        "s1",
        {"input_tokens": 5, "output_tokens": 2, "cost_usd": 0.01},
    )
    codex = [
        json.dumps({"type": "thread.started", "thread_id": "t1"}),
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 3, "output_tokens": 1}}
        ),
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 4, "output_tokens": 2}}
        ),
    ]
    assert parse_stream("codex", codex) == (
        "t1",
        {"input_tokens": 7, "output_tokens": 3},
    )


def test_environment_has_no_credentials_and_cannot_push(tmp_path, monkeypatch) -> None:
    for name in (
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "SSH_AUTH_SOCK",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setenv(name, "secret")
    env = scrubbed_environment(AGENT_COMMANDS["claude-code"], "sk-agent", str(tmp_path))
    assert not {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "AWS_SECRET_ACCESS_KEY",
        "SSH_AUTH_SOCK",
        "OPENAI_API_KEY",
    } & set(env)
    assert env["ANTHROPIC_API_KEY"] == "sk-agent" and env["HOME"] == str(tmp_path)
    # A real git push with this environment is rewritten to an unusable URL.
    root, _ = repository(tmp_path)
    git(root, "remote", "add", "origin", "https://github.com/example/never.git")
    pushed = subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=root,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert pushed.returncode != 0
    assert "dor-no-push" in pushed.stderr


# --------------------------------------------------------------------- #
# Running a package
# --------------------------------------------------------------------- #
def test_delivered_package_is_committed_attested_and_logged(setup, plan) -> None:
    root, base, bin_dir, store, adapter = setup
    fake_agent(bin_dir, "claude", CLAUDE_WRITES_RULES)
    result = run(adapter, plan, base)

    assert result.status == "delivered", result.reason
    assert result.affected_paths == ("src/rules/store.py", "tests/rules/test_store.py")
    assert git(root, "rev-parse", result.branch) == result.head_sha
    assert git(root, "log", "-1", "--format=%an", result.branch) == "DOR worker adapter"
    assert (
        git(root, "worktree", "list").count("\n") == 0
    )  # worktree removed, branch kept
    job = result.agent_job
    assert (job["role"], job["agent"]["brand"], job["session_id"]) == (
        "coder",
        "anthropic",
        "claude-session-1",
    )
    assert job["usage"] == {
        "input_tokens": 1200,
        "output_tokens": 300,
        "cost_usd": 0.04,
    }
    log = store.get(result.log_reference)
    assert log["status"] == "delivered" and "src/rules/store.py" in log["diff"]
    assert log["context_packet"]["work_package"]["logical_task_id"] == "module-rules"
    assert len(log["stream"]) == 2


def test_writing_outside_the_scope_rejects_the_delivery(setup, plan) -> None:
    _, base, bin_dir, store, adapter = setup
    fake_agent(
        bin_dir,
        "claude",
        CLAUDE_WRITES_RULES + "\npathlib.Path('README.md').write_text('hijacked')\n",
    )
    result = run(adapter, plan, base)
    assert result.status == "failed"
    assert "write scope" in result.reason and "README.md" in result.reason
    assert result.branch is None
    assert store.get(result.log_reference)["status"] == "failed"


def test_failed_attempts_are_rolled_back_and_regenerated(setup, plan) -> None:
    root, base, bin_dir, store, adapter = setup
    fake_agent(
        bin_dir,
        "claude",
        "pathlib.Path('src/rules').mkdir(parents=True)\npathlib.Path('src/rules/x.py').write_text('1')\nsys.exit(3)\n",
    )
    assert "exited with code 3" in run(adapter, plan, base).reason
    # The same attempt can run again: nothing from the failure is left behind.
    fake_agent(bin_dir, "claude", "print('{}')\n")
    assert run(adapter, plan, base).reason == "agent changed no files"
    fake_agent(bin_dir, "claude", "time.sleep(5)\n")
    result = run(adapter, plan, base, timeout_seconds=1)
    assert result.status == "failed" and "timed out" in result.reason
    assert git(root, "branch", "--list", "factory/*") == ""
    fake_agent(bin_dir, "claude", CLAUDE_WRITES_RULES)
    first = run(adapter, plan, base)
    regenerated = run(adapter, plan, base, attempt=2)
    assert first.status == regenerated.status == "delivered"
    assert first.branch.endswith("-a1") and regenerated.branch.endswith("-a2")
    assert regenerated.agent_job["provenance"]["attempt"] == 2
    assert store.get(regenerated.log_reference)["attempt"] == 2


def test_a_rework_round_starts_from_the_delivery_and_attests_from_the_base(
    setup, plan
) -> None:
    root, base, bin_dir, store, adapter = setup
    fake_agent(bin_dir, "claude", CLAUDE_WRITES_RULES)
    first = run(adapter, plan, base)
    fake_agent(
        bin_dir,
        "claude",
        "assert pathlib.Path('src/rules/store.py').exists()\n"
        "pathlib.Path('src/rules/store.py').write_text('def create():\\n    return 2\\n')\n",
    )
    findings = [{"id": "L-1", "target": "src/rules/store.py:2", "issue": "returns 1"}]
    rework = run(
        adapter,
        plan,
        base,
        attempt=2,
        start_sha=first.head_sha,
        rework_findings=findings,
    )
    assert rework.status == "delivered", rework.reason
    assert rework.affected_paths == ("src/rules/store.py", "tests/rules/test_store.py")
    assert (
        git(root, "merge-base", "--is-ancestor", first.head_sha, rework.head_sha) == ""
    )
    log = store.get(rework.log_reference)
    assert log["start_sha"] == first.head_sha and log["base_sha"] == base
    assert log["context_packet"]["rework"]["findings"] == findings
    assert "This is a rework round" in log["prompt"]
    assert (
        rework.agent_job["prompt_version"].count("coder/") == 2
    )  # task prompt + rework prompt
    # Writing outside the scope in a rework round fails like any other delivery.
    fake_agent(bin_dir, "claude", "pathlib.Path('README.md').write_text('x')\n")
    outside = run(
        adapter,
        plan,
        base,
        attempt=3,
        start_sha=rework.head_sha,
        rework_findings=findings,
    )
    assert outside.status == "failed" and "write scope" in outside.reason


def test_codex_runs_through_the_same_format(setup, plan) -> None:
    _, base, bin_dir, _, adapter = setup
    fake_agent(
        bin_dir,
        "codex",
        """
assert sys.argv[1:3] == ["exec", "--model"], sys.argv
print(json.dumps({"type": "thread.started", "thread_id": "codex-thread-9"}))
pathlib.Path("src/metrics").mkdir(parents=True, exist_ok=True)
pathlib.Path("src/metrics/record.py").write_text("x = 1\\n")
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}))
""",
    )
    result = run(
        adapter, plan, base, task_id="module-metrics", agent="codex", model="gpt-x"
    )
    assert result.status == "delivered", result.reason
    assert (result.agent_job["agent"]["brand"], result.agent_job["session_id"]) == (
        "openai",
        "codex-thread-9",
    )


def test_command_line_runs_one_package_from_a_pipeline_status(
    setup, plan, tmp_path, monkeypatch
) -> None:
    root, base, bin_dir, _, _ = setup
    fake_agent(bin_dir, "claude", CLAUDE_WRITES_RULES)
    monkeypatch.setenv("DOR_AGENT_LOG_DIR", str(tmp_path / "cli-logs"))
    status = tmp_path / "status.json"
    status.write_text(
        json.dumps(
            {
                "workflow_id": "wf-cli",
                "context": {
                    "work_plan": plan,
                    "contracts": contracts(),
                    "requirements": KRAVSPEC,
                },
            }
        )
    )
    code = main(
        [
            "--repo",
            str(root),
            "--base",
            base,
            "--status",
            str(status),
            "--package",
            "module-rules",
            "--agent",
            "claude-code",
        ]
    )
    assert code == 0


# --------------------------------------------------------------------- #
# Agent log store
# --------------------------------------------------------------------- #
def test_agent_log_is_content_addressed_immutable_and_verified(tmp_path) -> None:
    store = FileAgentLogStore(tmp_path)
    reference = store.put({"prompt": "p", "stream": ["a"]})
    assert store.put({"stream": ["a"], "prompt": "p"}) == reference
    assert store.get(reference) == {"prompt": "p", "stream": ["a"]}
    path = next(tmp_path.rglob("*.json"))
    assert not os.access(path, os.W_OK) or os.geteuid() == 0
    path.chmod(0o644)
    path.write_text('{"prompt": "tampered"}')
    with pytest.raises(AgentLogError, match="does not match"):
        store.get(reference)
