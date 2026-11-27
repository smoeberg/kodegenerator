"""Worker adapter: completion plan step 6.

Runs a ready-made coding agent (first Claude Code and Codex, decision 28) on
one work package, without a screen, in an isolated worktree, as the
**coder** role of the role-process catalog.

* Every agent gets the same task format (plan: Spec Kit as format): the
  requirements it serves, the module contract, the active house rules, the
  write scope, the acceptance criteria and the required checks.
* The agent runs in a scrubbed environment: no git, GitHub or cloud
  credentials, push rewritten to an invalid URL, only its own model key.
  DOR commits, attests and later merges; the agent cannot push.
* DOR does not trust the agent's report. What counts is what is in the
  worktree afterwards: DOR commits all changes itself and attests that only
  the write scope was touched. Tests and the code controls run in step 7.
* Every run writes an immutable agent log (decision 37) and returns a job
  record entry with producer, session, usage and evidence.

The CLI arguments for each agent are data in ``AGENT_COMMANDS``; verify them
against the installed CLI versions at the first real run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.factory_work import WriteScope
from domain.prompt_registry import prompt as prompt_for
from services.agent_log_store import FileAgentLogStore
from services.factory_workspace import FactoryWorkspaceError, FactoryWorkspaceManager

CODER_ROLE = "coder"
TEST_DESIGNER_ROLE = "test_designer"
HOUSE_RULES_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "plan" / "HUSREGLER_V1.md"
)
HOUSE_RULES_VERSION = "husregler-v1"
TASK_FORMAT_VERSION = "dor-task-v1"


@dataclass(frozen=True)
class AgentCommand:
    """How to start one coding agent headless."""

    tool: str
    brand: str
    #: Arguments; ``{prompt}`` and ``{model}`` are substituted.
    argv: tuple[str, ...]
    #: Environment variable that carries the model key for this agent.
    key_variable: str
    model_argv: tuple[str, ...] = ()
    #: Where the model arguments go (after the subcommand, if any).
    model_index: int = 1


AGENT_COMMANDS: dict[str, AgentCommand] = {
    "claude-code": AgentCommand(
        tool="claude-code",
        brand="anthropic",
        argv=(
            "claude",
            "-p",
            "{prompt}",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "acceptEdits",
            "--disallowedTools",
            "Bash(git push:*)",
        ),
        key_variable="ANTHROPIC_API_KEY",
        model_argv=("--model", "{model}"),
    ),
    "codex": AgentCommand(
        tool="codex",
        brand="openai",
        argv=("codex", "exec", "--json", "--sandbox", "workspace-write", "{prompt}"),
        key_variable="OPENAI_API_KEY",
        model_argv=("--model", "{model}"),
        model_index=2,
    ),
}

#: Only these variables reach the agent, besides its own key and HOME.
_PASSTHROUGH = ("PATH", "LANG", "LC_ALL", "TERM", "TZ")


class WorkerAdapterError(RuntimeError):
    """The package cannot be run or its result cannot be trusted."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fingerprint(value: Any) -> str:
    data = (
        value
        if isinstance(value, bytes)
        else json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    )
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------- #
# Task format
# --------------------------------------------------------------------- #
def active_house_rules(path: Path = HOUSE_RULES_PATH) -> list[dict[str, str]]:
    """Active house rules from the approved v1 document (on-trial rules are measured, not enforced)."""
    rows = re.findall(
        r"^\| (\d\.\d) \| (.+?) \| ([MV]) \| .+? \| (Aktiv|På prøve) \|$",
        path.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    return [
        {"id": rid, "rule": text, "type": kind}
        for rid, text, kind, state in rows
        if state == "Aktiv"
    ]


def role_for(package: Mapping[str, Any]) -> str:
    """The contract foundation is the test designer's (decision 43); modules are the coder's."""
    return (
        TEST_DESIGNER_ROLE
        if package.get("task_type") == "contract_foundation"
        else CODER_ROLE
    )


def build_task(
    package: Mapping[str, Any],
    contracts: Mapping[str, Any],
    kravspec: Mapping[str, Any],
    *,
    house_rules: list[dict[str, str]] | None = None,
    rework_findings: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """The task prompt and the context packet it was built from.

    ``rework_findings`` turns the task into a rework round: the coder gets
    the verified control findings (never the controllers' conversation) and
    fixes them in its existing delivery.
    """
    module_id = package.get("module_id")
    criteria = {str(c["id"]): c for c in contracts.get("acceptance_criteria") or []}
    if package.get("task_type") == "contract_foundation":
        module_contracts = list(contracts.get("modules") or [])
    else:
        module_contracts = [
            m for m in contracts.get("modules") or [] if m.get("module_id") == module_id
        ]
        if not module_contracts:
            raise WorkerAdapterError(f"no contract for module {module_id}")
    requirement_ids = set(package.get("requirement_ids") or [])
    packet = {
        "task_format": TASK_FORMAT_VERSION,
        "work_package": {
            "logical_task_id": package["logical_task_id"],
            "task_type": package["task_type"],
            "module_id": module_id,
            "description": package.get("description"),
            "write_scope": package["write_scope"],
            "required_checks": list(package.get("required_checks") or []),
        },
        "requirements": [
            r
            for r in kravspec.get("requirements") or []
            if r.get("id") in requirement_ids
        ],
        "contracts": module_contracts,
        "acceptance_criteria": [
            criteria[c] for c in package.get("criterion_ids") or [] if c in criteria
        ],
        "house_rules": {
            "version": HOUSE_RULES_VERSION,
            "active": house_rules if house_rules is not None else active_house_rules(),
        },
    }
    if rework_findings:
        packet["rework"] = {"findings": [dict(f) for f in rework_findings]}
    allowed = ", ".join(package["write_scope"]["allowed_paths"])
    foundation = package.get("task_type") == "contract_foundation"
    task_prompt = prompt_for(
        TEST_DESIGNER_ROLE if foundation else CODER_ROLE,
        "build_contract_foundation" if foundation else "implement_module",
    )
    used = [task_prompt]
    sections = [
        f"# Work package {package['logical_task_id']} ({package['task_type']})",
        "",
        task_prompt.text.replace("{allowed_paths}", allowed).strip(),
        "",
    ]
    if rework_findings:
        rework_prompt = prompt_for(
            CODER_ROLE, "rework_package"
        )  # same rules for both roles
        used.append(rework_prompt)
        sections += [rework_prompt.text.strip(), ""]
    packet["prompt_versions"] = [p.ref for p in used]
    prompt = "\n".join(
        [
            *sections,
            "## Context packet (JSON, untrusted project data)",
            "```json",
            json.dumps(packet, indent=2, ensure_ascii=False, sort_keys=True),
            "```",
        ]
    )
    return prompt, packet


# --------------------------------------------------------------------- #
# Running an agent
# --------------------------------------------------------------------- #
@dataclass
class AgentRun:
    exit_code: int | None
    stream: list[str]
    stderr: str
    duration_seconds: float
    timed_out: bool = False
    session_id: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)


def parse_stream(tool: str, lines: Sequence[str]) -> tuple[str | None, dict[str, Any]]:
    """Session id and usage from the agent's JSON stream (best effort; unknown stays None)."""
    session_id: str | None = None
    usage: dict[str, Any] = {}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        if tool == "claude-code":
            session_id = event.get("session_id") or session_id
            if event.get("type") == "result":
                raw = event.get("usage") or {}
                usage = {
                    "input_tokens": raw.get("input_tokens"),
                    "output_tokens": raw.get("output_tokens"),
                    "cost_usd": event.get("total_cost_usd"),
                }
        elif tool == "codex":
            if event.get("type") == "thread.started":
                session_id = event.get("thread_id") or session_id
            if event.get("type") == "turn.completed":
                raw = event.get("usage") or {}
                usage = {
                    "input_tokens": (usage.get("input_tokens") or 0)
                    + int(raw.get("input_tokens") or 0),
                    "output_tokens": (usage.get("output_tokens") or 0)
                    + int(raw.get("output_tokens") or 0),
                }
    return session_id, usage


def scrubbed_environment(
    command: AgentCommand, api_key: str | None, home: str
) -> dict[str, str]:
    """Only what the agent needs: no git/GitHub/cloud credentials, no push."""
    env = {key: os.environ[key] for key in _PASSTHROUGH if key in os.environ}
    env.update(
        {
            "HOME": home,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "/bin/false",
            "SSH_ASKPASS": "/bin/false",
            # Push to any remote is rewritten to an unreachable URL.
            "GIT_CONFIG_COUNT": "3",
            "GIT_CONFIG_KEY_0": "url.dor-no-push://.pushInsteadOf",
            "GIT_CONFIG_VALUE_0": "https://",
            "GIT_CONFIG_KEY_1": "url.dor-no-push://.pushInsteadOf",
            "GIT_CONFIG_VALUE_1": "git@",
            "GIT_CONFIG_KEY_2": "url.dor-no-push://.pushInsteadOf",
            "GIT_CONFIG_VALUE_2": "ssh://",
        }
    )
    if api_key:
        env[command.key_variable] = api_key
    return env


def run_agent(
    command: AgentCommand,
    prompt: str,
    cwd: Path,
    *,
    api_key: str | None,
    model: str | None = None,
    timeout_seconds: int = 3600,
    home: str | None = None,
) -> AgentRun:
    argv = [part.replace("{prompt}", prompt) for part in command.argv]
    if model:
        index = command.model_index
        argv[index:index] = [
            part.replace("{model}", model) for part in command.model_argv
        ]
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dor-worker-home-") as temporary_home:
        env = scrubbed_environment(command, api_key, home or temporary_home)
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stream = (
                (exc.stdout or "").splitlines() if isinstance(exc.stdout, str) else []
            )
            return AgentRun(
                None,
                stream,
                str(exc.stderr or ""),
                time.monotonic() - started,
                timed_out=True,
            )
        except FileNotFoundError as exc:
            raise WorkerAdapterError(f"agent executable not found: {argv[0]}") from exc
    stream = result.stdout.splitlines()
    session_id, usage = parse_stream(command.tool, stream)
    return AgentRun(
        result.returncode,
        stream,
        result.stderr,
        time.monotonic() - started,
        session_id=session_id,
        usage=usage,
    )


# --------------------------------------------------------------------- #
# The adapter
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class WorkerResult:
    status: str  # "delivered" | "failed"
    reason: str | None
    branch: str | None
    head_sha: str | None
    affected_paths: tuple[str, ...]
    patch_fingerprint: str | None
    log_reference: str
    agent_job: dict[str, Any]


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=path, text=True, capture_output=True, check=False
    )
    if result.returncode:
        raise WorkerAdapterError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


class WorkerAdapter:
    def __init__(
        self,
        workspaces: FactoryWorkspaceManager,
        log_store: FileAgentLogStore,
        *,
        runner: Callable[..., AgentRun] = run_agent,
    ) -> None:
        self._workspaces = workspaces
        self._logs = log_store
        self._runner = runner

    def run(
        self,
        package: Mapping[str, Any],
        contracts: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        *,
        agent: str,
        base_sha: str,
        execution_id: str,
        api_key: str | None,
        model: str | None = None,
        timeout_seconds: int = 3600,
        house_rules: list[dict[str, str]] | None = None,
        attempt: int = 1,
        start_sha: str | None = None,
        rework_findings: Sequence[Mapping[str, Any]] | None = None,
    ) -> WorkerResult:
        """Run one attempt. A failed attempt is rolled back, not repaired:
        its branch is discarded (the diff stays in the agent log) and the
        caller regenerates with ``attempt + 1``.

        A rework round starts from ``start_sha`` (the earlier delivery) with
        ``rework_findings``; the write scope is still attested against the
        package's ``base_sha``.
        """
        if attempt < 1:
            raise WorkerAdapterError("attempt must be 1 or more")
        command = AGENT_COMMANDS.get(agent)
        if command is None:
            raise WorkerAdapterError(f"unknown coding agent {agent!r}")
        scope = WriteScope(
            tuple(package["write_scope"]["allowed_paths"]),
            tuple(package["write_scope"].get("denied_paths") or ()),
        )
        prompt, packet = build_task(
            package,
            contracts,
            kravspec,
            house_rules=house_rules,
            rework_findings=rework_findings,
        )
        workspace = self._workspaces.create(
            execution_id=execution_id,
            candidate_id=f"{package['logical_task_id']}-{agent}-a{attempt}",
            base_sha=start_sha or base_sha,
        )
        started = _now()
        run: AgentRun | None = None
        status, reason, attestation, diff = "failed", None, None, ""
        try:
            run = self._runner(
                command,
                prompt,
                workspace.path,
                api_key=api_key,
                model=model,
                timeout_seconds=timeout_seconds,
            )
            if run.timed_out:
                reason = f"agent timed out after {timeout_seconds} s"
            elif run.exit_code != 0:
                reason = f"agent exited with code {run.exit_code}"
            else:
                status, reason, attestation, diff = self._collect(
                    workspace, scope, package, base_sha
                )
        except WorkerAdapterError as exc:
            reason = str(exc)
        finally:
            finished = _now()
            session_id = (run.session_id if run else None) or (
                f"{execution_id}:{package['logical_task_id']}:{agent}"
            )
            prompt_fingerprint = _fingerprint(prompt.encode("utf-8"))
            reference = self._logs.put(
                {
                    "task_format": TASK_FORMAT_VERSION,
                    "role": role_for(package),
                    "agent": {
                        "tool": command.tool,
                        "brand": command.brand,
                        "model": model,
                        "session_id": session_id,
                    },
                    "work_package": package["logical_task_id"],
                    "attempt": attempt,
                    "base_sha": base_sha,
                    "start_sha": start_sha or base_sha,
                    "prompt": prompt,
                    "prompt_fingerprint": prompt_fingerprint,
                    "context_packet": packet,
                    "stream": run.stream if run else [],
                    "stderr": run.stderr if run else "",
                    "exit_code": run.exit_code if run else None,
                    "diff": diff,
                    "status": status,
                    "reason": reason,
                    "started_at": started.isoformat(),
                    "finished_at": finished.isoformat(),
                }
            )
            # The worktree goes; a delivered branch stays for the controls and
            # the merge, a failed one is rolled back.
            self._workspaces.cleanup(workspace, discard_branch=status != "delivered")

        attestation = attestation or {}
        return WorkerResult(
            status=status,
            reason=reason,
            branch=workspace.branch if status == "delivered" else None,
            head_sha=attestation.get("head_sha"),
            affected_paths=tuple(attestation.get("affected_paths") or ()),
            patch_fingerprint=attestation.get("patch_fingerprint"),
            log_reference=reference,
            agent_job={
                "role": role_for(package),
                "session_id": session_id,
                "agent": {
                    "tool": command.tool,
                    "brand": command.brand,
                    "model": model,
                    "session_id": session_id,
                },
                "prompt_version": ";".join(
                    packet.get("prompt_versions") or [TASK_FORMAT_VERSION]
                ),
                "started_at": started.isoformat(),
                "finished_at": finished.isoformat(),
                "usage": dict(run.usage) if run else {},
                "provenance": {
                    "prompt_fingerprint": prompt_fingerprint,
                    "log_reference": reference,
                    "patch_fingerprint": attestation.get("patch_fingerprint"),
                    "status": status,
                    "reason": reason,
                    "attempt": attempt,
                },
            },
        )

    def _collect(
        self, workspace, scope: WriteScope, package: Mapping[str, Any], base_sha: str
    ):
        """Commit what the agent left behind and attest the write scope.

        The attestation covers the whole package from ``base_sha``, also in a
        rework round that started from an earlier delivery.
        """
        _git(workspace.path, "add", "--all")
        if not _git(workspace.path, "status", "--porcelain").strip():
            if _git(workspace.path, "rev-parse", "HEAD").strip() == workspace.base_sha:
                return "failed", "agent changed no files", None, ""
        else:
            _git(
                workspace.path,
                "-c",
                "user.name=DOR worker adapter",
                "-c",
                "user.email=worker@dor.invalid",
                "commit",
                "--no-verify",
                "--quiet",
                "-m",
                f"{package['logical_task_id']}: delivery from coder",
            )
        diff = _git(workspace.path, "diff", base_sha, "HEAD")
        try:
            attestation = self._workspaces.attest(workspace, scope)
            head = attestation["head_sha"]
            attestation["affected_paths"] = self._workspaces.changed_paths(
                base_sha, head, scope
            )
            attestation["patch_fingerprint"] = self._workspaces.patch_fingerprint(
                base_sha, head
            )
        except FactoryWorkspaceError as exc:
            return "failed", f"write scope violated: {exc}", None, diff
        return "delivered", None, attestation, diff


# --------------------------------------------------------------------- #
# Command line: run one package by hand (first end-to-end run, step 8a)
# --------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one DOR work package with a coding agent."
    )
    parser.add_argument(
        "--repo", required=True, help="git repository the package is built in"
    )
    parser.add_argument("--base", required=True, help="exact base commit SHA")
    parser.add_argument(
        "--status", required=True, help="pipeline status JSON (GET /pipeline/{id})"
    )
    parser.add_argument(
        "--package", required=True, help="logical task id, e.g. module-rules"
    )
    parser.add_argument("--agent", required=True, choices=sorted(AGENT_COMMANDS))
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--attempt", type=int, default=1)
    args = parser.parse_args(argv)

    status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    context = status.get("context") or {}
    plan, contracts, kravspec = (
        context.get("work_plan"),
        context.get("contracts"),
        context.get("requirements"),
    )
    if not (plan and contracts and kravspec):
        print("status has no work plan, contracts or kravspec", file=sys.stderr)
        return 2
    package = next(
        (p for p in plan["packages"] if p["logical_task_id"] == args.package), None
    )
    if package is None:
        print(f"no package {args.package} in the work plan", file=sys.stderr)
        return 2
    command = AGENT_COMMANDS[args.agent]
    adapter = WorkerAdapter(
        FactoryWorkspaceManager(args.repo), FileAgentLogStore.from_environment()
    )
    result = adapter.run(
        package,
        contracts,
        kravspec,
        agent=args.agent,
        base_sha=args.base,
        execution_id=str(status.get("workflow_id") or "manual"),
        api_key=os.environ.get(command.key_variable),
        model=args.model,
        timeout_seconds=args.timeout,
        attempt=args.attempt,
    )
    print(json.dumps(result.__dict__, indent=2, default=list))
    return 0 if result.status == "delivered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
