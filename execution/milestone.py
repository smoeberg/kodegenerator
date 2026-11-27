"""Completion plan step 8: the milestone branch.

``main`` is the common foundation; a milestone branch is a short-lived work
area on top of it (decision 34, section "Milestone-branches"):

* **Sprint start.** The milestone branch is rebased onto the newest ``main``
  and the whole suite runs before the day's packages are released. A
  conflict or a failing suite is an exception for the project manager; the
  branch is not moved. A start mark (tag) makes discarding the sprint a
  plain reset to it.
* **Binding.** Every package is bound to the commit it starts from, the
  kravspec revision and the contract version. Kravspec and contracts are
  frozen within a sprint.
* **Fan-out.** The packages of a sprint (independent by construction, with
  separate write scopes) run in parallel through the package line (step 7).
  Integration is serialized: when the milestone top has moved since a
  package started, the package is rebased onto the new top and controlled
  again; it is never assumed to fit. A package that no longer applies or
  fails the recheck is built again from the new top, once.
* **Review.** The project manager approves, corrects or discards the sprint;
  a discarded sprint resets the branch to its start mark and its packages
  are planned again.
* **Milestone.** Rebase onto the newest ``main``, full suite, level 2 on the
  whole milestone, the project manager's approval, one PR to ``main``.
  Merged: tag ``known-good/<milestone>`` on ``main``, a bundle of the
  repository and the factory state outside GitHub, and the milestone branch
  is deleted. Rolling back is a new branch from a known-good tag, never a
  rewrite of history.

The state is a versioned JSON document per milestone; every change is an
event with a time and an actor.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.prompt_registry import prompt
from domain.role_process import (
    RoleAssignment,
    RoleCatalog,
    RoleProcessError,
    default_catalog,
    validate_assignment,
)
from execution.package_control import (
    CONTEXT_CONTROLLER_ROLE,
    CRITERION_PATTERN,
    LEVEL2_SCHEMA,
    AgentChoice,
    PackageControl,
    PackageLine,
    criterion_ref,
    is_test_path,
    verify_findings,
)
from execution.role_dialogue import REVIEW_SCHEMA, call_role, fingerprint
from execution.statistics import milestone_statistics
from execution.task_compiler import CONTRACT_ROOT
from execution.worker_adapter import CODER_ROLE, TEST_DESIGNER_ROLE, WorkerResult
from services.bot_llm_runtime import BoundModel
from services.factory_workspace import FactoryWorkspaceError, FactoryWorkspaceManager

STATE_VERSION = 1
REVIEW_MODES = ("daily", "exceptions")
SPRINT_DECISIONS = ("approved", "corrected", "discarded")
_IDENTITY = {
    "GIT_AUTHOR_NAME": "DOR milestone",
    "GIT_AUTHOR_EMAIL": "milestone@dor.invalid",
    "GIT_COMMITTER_NAME": "DOR milestone",
    "GIT_COMMITTER_EMAIL": "milestone@dor.invalid",
}

WHOLE_LEVEL2_PROMPT = prompt("context_controller", "check_milestone")
SYSTEM_ARCHITECT_ROLE = "system_architect"
PRODUCT_OWNER_ROLE = "product_owner"
RELEASE_MANAGER_ROLE = "release_manager"
SYSTEM_ARCHITECT_PROMPT = prompt(SYSTEM_ARCHITECT_ROLE, "check_milestone")
PRODUCT_OWNER_PROMPT = prompt(PRODUCT_OWNER_ROLE, "check_mandate")
RELEASE_MANAGER_PROMPT = prompt(RELEASE_MANAGER_ROLE, "prepare_release")
RELEASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["ready", "not_ready"]},
        "release_notes": {"type": "string"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["recommendation", "release_notes", "reasons", "risks"],
}
#: Requirement ids (REG-01) and work package ids (module-rules) in free text.
_ID_IN_TEXT = re.compile(
    r"\b(?:[A-Z]{2,}-\d{2,}|module-[a-z0-9-]+|contract-foundation)\b"
)
WHOLE_LEVEL2_INSTRUCTIONS = WHOLE_LEVEL2_PROMPT.text


class MilestoneError(RuntimeError):
    """A milestone operation that is not allowed or cannot be done safely."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args],
        cwd=path,
        env={**os.environ, **_IDENTITY, "GIT_TERMINAL_PROMPT": "0"},
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        raise MilestoneError(result.stderr.strip() or f"git {args[0]} failed")
    return result


# --------------------------------------------------------------------- #
# State store
# --------------------------------------------------------------------- #
class FileMilestoneStore:
    """One versioned JSON document per milestone, replaced atomically."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @classmethod
    def from_environment(cls) -> FileMilestoneStore:
        return cls(os.getenv("DOR_MILESTONE_DIR", "./var/milestones"))

    def path(self, milestone_id: str) -> Path:
        if not milestone_id or "/" in milestone_id or milestone_id.startswith("."):
            raise MilestoneError("invalid milestone id")
        return self._root / f"{milestone_id}.json"

    def get(self, milestone_id: str) -> dict[str, Any]:
        path = self.path(milestone_id)
        if not path.exists():
            raise MilestoneError(f"no milestone {milestone_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def create(self, state: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            path = self.path(str(state["milestone_id"]))
            if path.exists():
                raise MilestoneError(
                    f"milestone {state['milestone_id']} already exists"
                )
            return self._write(path, {**state, "revision": 1})

    def put(self, state: Mapping[str, Any]) -> dict[str, Any]:
        """Replace the state if nobody changed it since it was read."""
        with self._lock:
            path = self.path(str(state["milestone_id"]))
            current = json.loads(path.read_text(encoding="utf-8"))
            if current["revision"] != state["revision"]:
                raise MilestoneError("milestone state changed concurrently")
            return self._write(path, {**state, "revision": state["revision"] + 1})

    @staticmethod
    def _write(path: Path, state: dict[str, Any]) -> dict[str, Any]:
        handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            json.dump(state, file, indent=2, sort_keys=True)
        os.replace(temporary, path)
        return state


def _event(state: dict[str, Any], kind: str, actor: str, **details: Any) -> None:
    state.setdefault("events", []).append(
        {"at": _now(), "kind": kind, "actor": actor, **details}
    )


# --------------------------------------------------------------------- #
# The factory's full suite
# --------------------------------------------------------------------- #
SuiteRunner = Callable[[Path, Sequence[str]], dict[str, Any]]


def run_full_suite(
    path: Path, ignore: Sequence[str] = (), *, timeout: int = 3600
) -> dict[str, Any]:
    """Run the whole test suite of a checked-out revision, without credentials.

    ``ignore`` holds contract test files of modules that are not merged yet:
    they fail by design until their module exists.
    """
    with tempfile.TemporaryDirectory(prefix="dor-suite-home-") as home:
        env = {
            k: os.environ[k]
            for k in ("PATH", "LANG", "LC_ALL", "TZ")
            if k in os.environ
        }
        env.update(HOME=home, PYTHONDONTWRITEBYTECODE="1")
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *(f"--ignore={p}" for p in ignore),
        ]
        try:
            done = subprocess.run(
                command,
                cwd=path,
                env=env,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "exit_code": None,
                "output": f"timed out after {timeout} s",
            }
    output = (done.stdout or "") + (done.stderr or "")
    # pytest exit code 5: no tests collected; an empty milestone is not "green".
    return {
        "status": "passed" if done.returncode == 0 else "failed",
        "exit_code": done.returncode,
        "command": command,
        "output": output[-8000:],
    }


# --------------------------------------------------------------------- #
# The milestone
# --------------------------------------------------------------------- #
class MilestoneRunner:
    def __init__(
        self,
        workspaces: FactoryWorkspaceManager,
        line: PackageLine,
        control: PackageControl,
        store: FileMilestoneStore,
        *,
        suite_runner: SuiteRunner = run_full_suite,
        whole_controller: BoundModel | None = None,
        governance: Mapping[str, BoundModel] | None = None,
        catalog: RoleCatalog | None = None,
        main_ref: str = "main",
        max_parallel: int | None = None,
    ) -> None:
        self._workspaces = workspaces
        self._line = line
        self._control = control
        self._store = store
        self._suite = suite_runner
        self._whole_controller = whole_controller
        #: Governance agents on the milestone (decision 40): system_architect,
        #: product_owner, release_manager. They recommend; the board decides.
        self._governance = dict(governance or {})
        self._catalog = catalog or default_catalog()
        self._main_ref = main_ref
        self._max_parallel = max_parallel or int(
            os.getenv("DOR_MAX_PARALLEL_PACKAGES", "4")
        )
        self._integration = threading.Lock()

    # ----------------------------------------------------------------- #
    def _main(self) -> str:
        sha = self._workspaces.resolve(self._main_ref)
        if not sha:
            raise MilestoneError(f"{self._main_ref} does not resolve")
        return sha

    def _top(self, state: Mapping[str, Any]) -> str:
        sha = self._workspaces.resolve(f"refs/heads/{state['branch']}")
        if not sha:
            raise MilestoneError(f"milestone branch {state['branch']} is missing")
        return sha

    def start(
        self,
        plan: Mapping[str, Any],
        *,
        requirements_fingerprint: str,
        actor: str,
        review_mode: str = "daily",
    ) -> dict[str, Any]:
        """Create the milestone branch on the newest ``main``."""
        if review_mode not in REVIEW_MODES:
            raise MilestoneError(f"review mode must be one of {REVIEW_MODES}")
        if (plan.get("scaling_plan") or {}).get("status") not in {
            "approved",
            "awaiting_approval",
        }:
            raise MilestoneError("the work plan has no scaling plan")
        milestone_id = str(plan["milestone_id"])
        branch = f"milestone/{milestone_id}"
        main = self._main()
        self._workspaces.update_ref(f"refs/heads/{branch}", main, None)
        state: dict[str, Any] = {
            "state_version": STATE_VERSION,
            "milestone_id": milestone_id,
            "branch": branch,
            "status": "running",
            "review_mode": review_mode,
            "main_sha_at_start": main,
            "work_plan_fingerprint": plan.get("fingerprint"),
            "contract_fingerprint": plan.get("contract_fingerprint"),
            "requirements_fingerprint": requirements_fingerprint,
            "sprint_plan": [dict(s) for s in plan["sprints"]],
            "packages": {
                p["logical_task_id"]: {
                    "status": "pending",
                    "sprint": p.get("sprint"),
                    "dependency_ids": list(p.get("dependency_ids") or []),
                    "task_type": p.get("task_type"),
                    "criterion_ids": list(p.get("criterion_ids") or []),
                }
                for p in plan["packages"]
            },
            "sprints": [],
        }
        _event(state, "milestone_started", actor, main_sha=main)
        return self._store.create(state)

    # ----------------------------------------------------------------- #
    def change_input(
        self,
        milestone_id: str,
        *,
        actor: str,
        requirements_fingerprint: str | None = None,
        contract_fingerprint: str | None = None,
    ) -> dict[str, Any]:
        """Record an approved change of kravspec or contracts; it applies at the next sprint start."""
        if not (requirements_fingerprint or contract_fingerprint):
            raise MilestoneError(
                "an input change names a new kravspec or contract version"
            )
        state = self._store.get(milestone_id)
        self._require_running(state)
        pending = dict(state.get("pending_input") or {})
        if requirements_fingerprint:
            pending["requirements_fingerprint"] = requirements_fingerprint
        if contract_fingerprint:
            pending["contract_fingerprint"] = contract_fingerprint
        state["pending_input"] = pending
        _event(state, "input_change_recorded", actor, **pending)
        return self._store.put(state)

    # ----------------------------------------------------------------- #
    def start_sprint(
        self, milestone_id: str, sprint: int, *, actor: str
    ) -> dict[str, Any]:
        """Rebase onto the newest ``main``, run the suite, set the start mark."""
        state = self._store.get(milestone_id)
        self._require_running(state)
        planned = {s["sprint"]: s for s in state["sprint_plan"]}
        if sprint not in planned:
            raise MilestoneError(f"sprint {sprint} is not in the plan")
        current = self._current_sprint(state)
        if current and current["status"] in {"started", "running"}:
            raise MilestoneError(f"sprint {current['sprint']} is still running")
        if (
            current
            and current["status"] == "awaiting_review"
            and (state["review_mode"] == "daily" or current.get("exceptions"))
        ):
            raise MilestoneError(
                f"sprint {current['sprint']} awaits the project manager's review"
            )
        waiting = [
            dep
            for task in planned[sprint]["packages"]
            for dep in state["packages"][task]["dependency_ids"]
            if state["packages"][dep]["status"] != "merged"
        ]
        if waiting:
            raise MilestoneError(
                f"sprint {sprint} depends on unmerged packages {sorted(set(waiting))}"
            )

        top, main = self._top(state), self._main()
        record: dict[str, Any] = {
            "sprint": sprint,
            "run": 1 + sum(1 for s in state["sprints"] if s["sprint"] == sprint),
            "main_sha": main,
            "started_at": _now(),
            "packages": {},
            "frozen": {
                "requirements_fingerprint": state["requirements_fingerprint"],
                "contract_fingerprint": state["contract_fingerprint"],
            },
        }
        new_top, problem, suite = self._rebased_and_tested(top, main, state)
        record["suite"] = suite
        if problem:
            record.update(status="exception", reason=problem)
            state["sprints"].append(record)
            _event(state, "sprint_exception", actor, sprint=sprint, reason=problem)
            return self._store.put(state)
        if new_top != top:
            self._workspaces.update_ref(f"refs/heads/{state['branch']}", new_top, top)
        pending = state.pop("pending_input", None)
        if pending:
            # Frozen within a sprint; a change takes effect here. Merged packages bound
            # to the old version go to the change process, they are not silently kept.
            state.update(pending)
            record["frozen"] = {
                "requirements_fingerprint": state["requirements_fingerprint"],
                "contract_fingerprint": state["contract_fingerprint"],
            }
            record["bound_to_old_input"] = sorted(
                task
                for task, item in state["packages"].items()
                if item.get("binding")
                and any(item["binding"][k] != v for k, v in record["frozen"].items())
            )
        tag = f"refs/tags/dor-sprint/{milestone_id}/{sprint}-run{record['run']}-start"
        self._workspaces.update_ref(tag, new_top, None)
        record.update(status="started", start_sha=new_top, start_tag=tag)
        state["sprints"].append(record)
        _event(state, "sprint_started", actor, sprint=sprint, start_sha=new_top)
        return self._store.put(state)

    def _unbuilt_contract_tests(self, state: Mapping[str, Any], sha: str) -> list[str]:
        """Contract test files that only test modules which are not merged yet."""
        pending = {
            criterion.upper()
            for item in state["packages"].values()
            if item.get("task_type") != "contract_foundation"
            and item["status"] != "merged"
            for criterion in item.get("criterion_ids") or []
        }
        ignore = []
        for path in self._workspaces.list_files(sha, CONTRACT_ROOT):
            if not is_test_path(path):
                continue
            text = self._workspaces.read_file(sha, path) or ""
            refs = {criterion_ref(m.group(0)) for m in CRITERION_PATTERN.finditer(text)}
            if refs and refs <= pending:
                ignore.append(path)
        return ignore

    def _rebased_and_tested(
        self, top: str, main: str, state: Mapping[str, Any]
    ) -> tuple[str, str | None, dict | None]:
        """Rebase ``top`` onto ``main`` in a throw-away worktree and run the suite there."""
        with self._workspaces.checkout(top) as path:
            if not self._workspaces.is_ancestor(main, top):
                rebased = _git(path, "rebase", main, check=False)
                if rebased.returncode:
                    _git(path, "rebase", "--abort", check=False)
                    return top, f"rebase onto main {main[:12]} conflicts", None
            new_top = _git(path, "rev-parse", "HEAD").stdout.strip()
            ignore = self._unbuilt_contract_tests(state, new_top)
            suite = {**self._suite(path, ignore), "ignored": ignore}
        if suite["status"] != "passed":
            return (
                top,
                f"the full suite fails after rebasing onto main {main[:12]}",
                suite,
            )
        return new_top, None, suite

    # ----------------------------------------------------------------- #
    def run_sprint(
        self,
        milestone_id: str,
        sprint: int,
        plan: Mapping[str, Any],
        contracts: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        *,
        coder: AgentChoice | Callable[[Mapping[str, Any]], AgentChoice],
        fresh_coder: AgentChoice | None,
        execution_id: str,
        organization_id: str,
        actor_id: str,
        architecture: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the sprint's packages in parallel and integrate them one by one."""
        state = self._store.get(milestone_id)
        record = self._current_sprint(state)
        if not record or record["sprint"] != sprint or record["status"] != "started":
            raise MilestoneError(f"sprint {sprint} has not been started")
        if plan.get("fingerprint") != state["work_plan_fingerprint"]:
            raise MilestoneError(
                "the work plan is not the one the milestone was started on"
            )
        if fingerprint(dict(contracts)) != state["contract_fingerprint"]:
            raise MilestoneError(
                "the contracts are not the ones the milestone was planned on"
            )
        record["status"] = "running"
        state = self._store.put(state)

        packages = {p["logical_task_id"]: p for p in plan["packages"]}
        tasks = [packages[t] for t in record_plan(state, sprint)]
        context = {
            "contracts": contracts,
            "kravspec": kravspec,
            "fresh_coder": fresh_coder,
            "execution_id": execution_id,
            "organization_id": organization_id,
            "actor_id": actor_id,
            "architecture": architecture,
            "run_id": f"s{sprint}r{record['run']}",
        }
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(
            max_workers=max(1, min(self._max_parallel, len(tasks)))
        ) as pool:
            futures = {
                pool.submit(
                    self._deliver_and_integrate,
                    milestone_id,
                    package,
                    coder(package) if callable(coder) else coder,
                    record["frozen"],
                    context,
                ): package["logical_task_id"]
                for package in tasks
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()

        state = self._store.get(milestone_id)
        record = self._current_sprint(state)
        exceptions = []
        for task_id, result in sorted(results.items()):
            record["packages"][task_id] = result
            state["packages"][task_id].update(
                status=result["status"],
                binding=result.get("binding"),
                merged_sha=result.get("merged_sha"),
                delivered_by=result.get("delivered_by"),
            )
            if result["status"] != "merged":
                exceptions.append(task_id)
        record.update(
            status="awaiting_review", exceptions=exceptions, finished_at=_now()
        )
        _event(state, "sprint_finished", actor_id, sprint=sprint, exceptions=exceptions)
        return self._store.put(state)

    def _deliver_and_integrate(
        self,
        milestone_id: str,
        package: Mapping[str, Any],
        coder: AgentChoice,
        frozen: Mapping[str, str],
        context: Mapping[str, Any],
        *,
        redelivered: bool = False,
    ) -> dict[str, Any]:
        state = self._store.get(milestone_id)
        start = self._top(state)
        binding = {"start_sha": start, **frozen}
        outcome = self._line.deliver(
            package,
            context["contracts"],
            context["kravspec"],
            coder=coder,
            fresh_coder=context["fresh_coder"],
            base_sha=start,
            execution_id=context["execution_id"],
            organization_id=context["organization_id"],
            actor_id=context["actor_id"],
            architecture=context["architecture"],
            test_designer=self._test_designer(state),
            run_id=f"{milestone_id}-{context['run_id']}"
            + ("-rebuild" if redelivered else ""),
        )
        summary = {
            "binding": binding,
            "package_outcome": {
                k: outcome[k] for k in ("status", "reason", "measurements")
            },
            "attempts": outcome["attempts"],
            "agent_jobs": list(outcome["agent_jobs"]),
            "redelivered": redelivered,
        }
        if outcome["status"] != "passed":
            return {**summary, "status": outcome["status"]}
        integrated = self._integrate(milestone_id, package, outcome, binding, context)
        if integrated["status"] == "rebuild" and not redelivered:
            again = self._deliver_and_integrate(
                milestone_id, package, coder, frozen, context, redelivered=True
            )
            again["earlier"] = {**summary, **integrated}
            return again
        if integrated["status"] == "rebuild":
            integrated["status"] = "escalated"
        return {
            **summary,
            **integrated,
            "agent_jobs": summary["agent_jobs"] + integrated.pop("agent_jobs", []),
        }

    def _integrate(
        self,
        milestone_id: str,
        package: Mapping[str, Any],
        outcome: Mapping[str, Any],
        binding: Mapping[str, str],
        context: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Merge one controlled package; rebase and control again if the top moved."""
        with self._integration:
            state = self._store.get(milestone_id)
            sprint = self._current_sprint(state)
            branch = str(outcome["branch"])
            head = str(outcome["head_sha"])
            current = {
                "requirements_fingerprint": state["requirements_fingerprint"],
                "contract_fingerprint": state["contract_fingerprint"],
            }
            if sprint["status"] != "running" or any(
                current[k] != binding[k] for k in current
            ):
                self._workspaces.discard_branch(branch)
                return {
                    "status": "stale",
                    "reason": "kravspec or contracts changed since the package started",
                }
            top = self._top(state)
            result: dict[str, Any] = {"agent_jobs": [], "rechecked": False}
            if top != binding["start_sha"]:
                rebased = self._rebase_package(
                    head, onto=top, upstream=binding["start_sha"]
                )
                if rebased is None:
                    self._workspaces.discard_branch(branch)
                    return {
                        "status": "rebuild",
                        "reason": "the package does not apply to the new milestone top",
                    }
                delivery = outcome["delivery"]
                recheck = self._control.check(
                    WorkerResult(
                        status="delivered",
                        reason=None,
                        branch=branch,
                        head_sha=rebased,
                        affected_paths=tuple(delivery["affected_paths"]),
                        patch_fingerprint=None,
                        log_reference=delivery["log_reference"],
                        agent_job=delivery["coder_job"],
                    ),
                    package,
                    context["contracts"],
                    context["kravspec"],
                    base_sha=top,
                    organization_id=context["organization_id"],
                    actor_id=context["actor_id"],
                    run_key=f"{context['execution_id']}:{package['logical_task_id']}:recheck:{rebased[:12]}",
                    architecture=context["architecture"],
                    test_designer=self._test_designer(state),
                )
                result["agent_jobs"] = list(recheck.get("agent_jobs") or [])
                result["recheck"] = {
                    k: recheck.get(k) for k in ("status", "stage", "cause", "findings")
                }
                if recheck["status"] != "passed":
                    self._workspaces.discard_branch(branch)
                    return {
                        **result,
                        "status": "rebuild",
                        "reason": f"recheck on the new top: {recheck.get('stage')} {recheck['status']}",
                    }
                head, result["rechecked"] = rebased, True
            if not self._workspaces.is_ancestor(top, head):
                raise MilestoneError("a package to merge must sit on the milestone top")
            try:
                self._workspaces.update_ref(f"refs/heads/{state['branch']}", head, top)
            except FactoryWorkspaceError as exc:
                raise MilestoneError(
                    f"milestone top moved during integration: {exc}"
                ) from exc
            self._workspaces.discard_branch(branch)
            return {
                **result,
                "status": "merged",
                "merged_sha": head,
                "delivered_by": {
                    "role": outcome["delivery"]["coder_job"].get("role"),
                    "brand": outcome["delivery"]["coder_job"]["agent"]["brand"],
                    "tool": outcome["delivery"]["coder_job"]["agent"].get("tool"),
                    "session_id": outcome["delivery"]["coder_job"]["session_id"],
                },
                "binding": {**binding, "start_sha": top}
                if result["rechecked"]
                else dict(binding),
                "reason": "merged"
                + (" after rebase and recheck" if result["rechecked"] else ""),
            }

    @staticmethod
    def _test_designer(state: Mapping[str, Any]) -> dict[str, Any] | None:
        """Who wrote the merged contract foundation, the acceptance tests modules are judged by."""
        for item in state["packages"].values():
            if (
                item.get("task_type") == "contract_foundation"
                and item["status"] == "merged"
            ):
                return item.get("delivered_by")
        return None

    def _rebase_package(self, head: str, *, onto: str, upstream: str) -> str | None:
        with self._workspaces.checkout(head) as path:
            done = _git(path, "rebase", "--onto", onto, upstream, check=False)
            if done.returncode:
                _git(path, "rebase", "--abort", check=False)
                return None
            return _git(path, "rev-parse", "HEAD").stdout.strip()

    # ----------------------------------------------------------------- #
    def review_sprint(
        self,
        milestone_id: str,
        sprint: int,
        decision: str,
        *,
        reviewer: str,
        note: str = "",
    ) -> dict[str, Any]:
        """The project manager approves, corrects or discards the sprint."""
        if decision not in SPRINT_DECISIONS:
            raise MilestoneError(f"decision must be one of {SPRINT_DECISIONS}")
        if not reviewer:
            raise MilestoneError("a sprint review needs a reviewer")
        state = self._store.get(milestone_id)
        record = self._current_sprint(state)
        if (
            not record
            or record["sprint"] != sprint
            or record["status"]
            not in {
                "awaiting_review",
                "exception",
            }
        ):
            raise MilestoneError(f"sprint {sprint} is not awaiting review")
        if decision == "discarded" and record.get("start_sha"):
            top = self._top(state)
            if top != record["start_sha"]:
                self._workspaces.update_ref(
                    f"refs/heads/{state['branch']}", record["start_sha"], top
                )
            planned = next(p for p in state["sprint_plan"] if p["sprint"] == sprint)
            for task_id in planned["packages"]:
                state["packages"][task_id].update(
                    status="pending", binding=None, merged_sha=None
                )
        elif decision in {"approved", "corrected"}:
            # Corrected: deviations become new work in a later sprint run.
            for task_id in record.get("exceptions") or []:
                state["packages"][task_id]["status"] = "pending"
        record.update(
            status=decision, reviewed_by=reviewer, review_note=note, reviewed_at=_now()
        )
        _event(state, "sprint_reviewed", reviewer, sprint=sprint, decision=decision)
        return self._store.put(state)

    # ----------------------------------------------------------------- #
    def finish(
        self,
        milestone_id: str,
        contracts: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        *,
        organization_id: str,
        actor_id: str,
        architecture: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebase onto the newest ``main``, full suite, level 2 on the whole, the
        system architect, the product owner and the release manager."""
        state = self._store.get(milestone_id)
        self._require_running(state)
        open_packages = [
            t for t, p in state["packages"].items() if p["status"] != "merged"
        ]
        if open_packages:
            raise MilestoneError(f"packages are not merged: {sorted(open_packages)}")
        last = self._current_sprint(state)
        if state["review_mode"] == "daily" and (
            not last or last["status"] not in {"approved", "corrected"}
        ):
            raise MilestoneError("the last sprint has not been reviewed")
        top, main = self._top(state), self._main()
        new_top, problem, suite = self._rebased_and_tested(top, main, state)
        review: dict[str, Any] = {"main_sha": main, "suite": suite, "at": _now()}
        if problem:
            review.update(status="exception", reason=problem)
        else:
            if new_top != top:
                self._workspaces.update_ref(
                    f"refs/heads/{state['branch']}", new_top, top
                )
            review.update(
                head_sha=new_top,
                **self._milestone_stages(
                    state,
                    new_top,
                    main,
                    contracts,
                    kravspec,
                    organization_id,
                    actor_id,
                    architecture or {},
                ),
            )
        state["milestone_review"] = review
        state["status"] = (
            "awaiting_approval" if review["status"] == "passed" else "running"
        )
        _event(state, "milestone_reviewed", actor_id, status=review["status"])
        return self._store.put(state)

    def _milestone_stages(
        self,
        state: Mapping[str, Any],
        head: str,
        main: str,
        contracts: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        organization_id: str,
        actor_id: str,
        architecture: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Level 2 on the whole, then the system architect and the product owner,
        then the release checklist and the release manager. Each stage runs only
        when the one before it passed; every model comes from a producer
        independent of all coders and the test designer."""
        paths = self._workspaces.changed_paths(main, head)
        files = {
            p: t
            for p in paths
            if (t := self._workspaces.read_file(head, p)) is not None
        }
        requirement_ids = {str(r.get("id")) for r in kravspec.get("requirements") or []}
        criterion_ids = {
            str(c["id"]) for c in contracts.get("acceptance_criteria") or []
        }
        module_ids = {str(m.get("module_id")) for m in contracts.get("modules") or []}
        diff = self._workspaces.diff(main, head)
        base_packet = {
            "milestone_id": state["milestone_id"],
            "diff": diff,
            "changed_paths": list(paths),
            "requirements": list(kravspec.get("requirements") or []),
            "acceptance_criteria": list(contracts.get("acceptance_criteria") or []),
            "contracts": list(contracts.get("modules") or []),
            "factory_test_results": {"full_suite": "passed"},
        }
        stages: dict[str, Any] = {}
        jobs: list[dict[str, Any]] = []

        def outcome(status: str, reason: str | None = None) -> dict[str, Any]:
            last = next(reversed(stages.values()), {}) if stages else {}
            return {
                "status": status,
                "reason": reason or last.get("reason"),
                "stages": stages,
                "findings": [
                    f for st in stages.values() for f in st.get("findings") or []
                ],
                "open_findings": [
                    f for st in stages.values() for f in st.get("open_findings") or []
                ],
                "rejected_findings": [
                    f
                    for st in stages.values()
                    for f in st.get("rejected_findings") or []
                ],
                "agent_jobs": jobs,
            }

        reviews = (
            (
                "level2",
                CONTEXT_CONTROLLER_ROLE,
                self._whole_controller,
                WHOLE_LEVEL2_PROMPT,
                LEVEL2_SCHEMA,
                {},
            ),
            (
                "architecture",
                SYSTEM_ARCHITECT_ROLE,
                self._governance.get(SYSTEM_ARCHITECT_ROLE),
                SYSTEM_ARCHITECT_PROMPT,
                REVIEW_SCHEMA,
                {"approved_architecture": dict(architecture)},
            ),
            (
                "mandate",
                PRODUCT_OWNER_ROLE,
                self._governance.get(PRODUCT_OWNER_ROLE),
                PRODUCT_OWNER_PROMPT,
                LEVEL2_SCHEMA,
                {"criteria_tested": self._criteria_tested(head, criterion_ids)},
            ),
        )
        for name, role, model, role_prompt, schema, extra in reviews:
            packet = {
                **base_packet,
                **extra,
                "earlier_stages": {
                    k: {key: v.get(key) for key in ("status", "findings")}
                    for k, v in stages.items()
                },
            }
            stage = self._stage_review(
                state,
                head,
                role,
                model,
                role_prompt,
                schema,
                packet,
                files,
                requirement_ids | criterion_ids | module_ids,
                requirement_ids,
                organization_id,
                actor_id,
                name,
            )
            jobs.extend(stage.pop("agent_jobs", []))
            stages[name] = stage
            if stage["status"] != "passed":
                return outcome(stage["status"])

        checklist = self._release_checklist(state, head, criterion_ids, stages)
        statistics = milestone_statistics(
            {**state, "milestone_review": {"agent_jobs": jobs}}
        )
        stages["checklist"] = {
            "status": "passed" if all(i["holds"] for i in checklist) else "failed",
            "items": checklist,
            "reason": None
            if all(i["holds"] for i in checklist)
            else "release checklist: "
            + ", ".join(i["item"] for i in checklist if not i["holds"]),
        }
        if stages["checklist"]["status"] != "passed":
            return outcome("failed")
        release = self._release_notes(
            state,
            head,
            checklist,
            statistics,
            stages,
            kravspec,
            organization_id,
            actor_id,
        )
        jobs.extend(release.pop("agent_jobs", []))
        stages["release"] = release
        result = outcome(release["status"])
        # Final numbers include the release manager's own job.
        result["statistics"] = milestone_statistics(
            {**state, "milestone_review": {"agent_jobs": jobs}}
        )
        return result

    def _independence(
        self, state: Mapping[str, Any], role: str, model: BoundModel
    ) -> str | None:
        builders = {
            (job["agent"]["brand"], job["session_id"])
            for sprint in state["sprints"]
            for result in (sprint.get("packages") or {}).values()
            if result.get("status") == "merged"
            for job in result.get("agent_jobs") or []
            if job.get("role") in {CODER_ROLE, TEST_DESIGNER_ROLE}
        }
        for brand, session in sorted(builders):
            if brand == model.identity.brand:
                return (
                    f"{role} must come from a different producer than the code it judges "
                    f"({brand} built part of the milestone, session {session})"
                )
        try:
            validate_assignment(
                self._catalog,
                RoleAssignment(
                    role,
                    state["milestone_id"],
                    role,
                    model.identity.brand,
                    f"{state['milestone_id']}:{role}",
                ),
                [
                    RoleAssignment(
                        f"coder-{i}", state["milestone_id"], CODER_ROLE, brand, session
                    )
                    for i, (brand, session) in enumerate(sorted(builders))
                ],
            )
        except RoleProcessError as exc:
            return str(exc)
        return None

    def _stage_review(
        self,
        state,
        head,
        role,
        model,
        role_prompt,
        schema,
        packet,
        files,
        targets,
        requirement_ids,
        organization_id,
        actor_id,
        name,
    ) -> dict[str, Any]:
        if model is None:
            return {"status": "waiting", "reason": f"no {role} for the milestone"}
        problem = self._independence(state, role, model)
        if problem:
            return {"status": "waiting", "reason": problem}
        review, turn = call_role(
            model,
            purpose=f"milestone:{role}",
            role=role,
            round_number=1,
            instructions=role_prompt.text,
            schema=schema,
            context_packet=packet,
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=f"{state['milestone_id']}:{head[:12]}:{name}",
            prompt_version=role_prompt.ref,
        )
        verified, rejected = verify_findings(
            review, files=files, other_targets=targets, requirement_ids=requirement_ids
        )
        open_findings = [
            {**f, "source": role}
            for f in verified
            if f["severity"] in {"blocking", "major"}
        ]
        causes = {f.get("cause") for f in open_findings}
        return {
            "status": "passed" if not open_findings else "failed",
            "role": role,
            "verdict": review.get("verdict"),
            "cause": None
            if not open_findings
            else ("input" if "input" in causes else "code"),
            "reason": None
            if not open_findings
            else f"{name}: {len(open_findings)} open findings",
            "findings": verified,
            "open_findings": open_findings,
            "rejected_findings": rejected,
            "agent_jobs": [turn.job()],
        }

    def _criteria_tested(
        self, head: str, criterion_ids: set[str]
    ) -> dict[str, list[str]]:
        """Which acceptance tests at the milestone head name each criterion."""
        tested: dict[str, list[str]] = {c: [] for c in sorted(criterion_ids)}
        for path in self._workspaces.list_files(head):
            if not is_test_path(path):
                continue
            text = self._workspaces.read_file(head, path) or ""
            for ref in {
                criterion_ref(m.group(0)) for m in CRITERION_PATTERN.finditer(text)
            }:
                if ref in tested:
                    tested[ref].append(path)
        return tested

    def _release_checklist(
        self,
        state: Mapping[str, Any],
        head: str,
        criterion_ids: set[str],
        stages: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Computed by the system; the release manager only writes from it."""
        tested = self._criteria_tested(head, criterion_ids)
        acceptance = {
            c: [p for p in paths if p.startswith(f"{CONTRACT_ROOT}/")]
            for c, paths in tested.items()
        }
        secrets = sum(
            ((result.get("package_outcome") or {}).get("measurements") or {}).get(
                "secrets_found"
            )
            or 0
            for sprint in state["sprints"]
            for result in (sprint.get("packages") or {}).values()
            if result.get("status") == "merged"
        )
        return [
            {
                "item": "all packages merged",
                "holds": all(
                    p["status"] == "merged" for p in state["packages"].values()
                ),
            },
            {"item": "full suite passed on the rebased milestone", "holds": True},
            {
                "item": "level 2 on the whole passed",
                "holds": stages["level2"]["status"] == "passed",
            },
            {
                "item": "system architect passed",
                "holds": stages["architecture"]["status"] == "passed",
            },
            {
                "item": "product owner passed",
                "holds": stages["mandate"]["status"] == "passed",
            },
            {
                "item": "every acceptance criterion has an acceptance test",
                "holds": all(acceptance.values()),
                "missing": sorted(c for c, paths in acceptance.items() if not paths),
            },
            {"item": "no secrets in merged deliveries", "holds": secrets == 0},
        ]

    def _release_notes(
        self,
        state,
        head,
        checklist,
        statistics,
        stages,
        kravspec,
        organization_id,
        actor_id,
    ) -> dict[str, Any]:
        model = self._governance.get(RELEASE_MANAGER_ROLE)
        if model is None:
            return {
                "status": "waiting",
                "reason": f"no {RELEASE_MANAGER_ROLE} for the milestone",
            }
        value, turn = call_role(
            model,
            purpose=f"milestone:{RELEASE_MANAGER_ROLE}",
            role=RELEASE_MANAGER_ROLE,
            round_number=1,
            instructions=RELEASE_MANAGER_PROMPT.text,
            schema=RELEASE_SCHEMA,
            context_packet={
                "milestone_id": state["milestone_id"],
                "checklist": checklist,
                "statistics": {k: v for k, v in statistics.items() if k != "packages"}
                | {
                    "packages": {
                        k: v for k, v in statistics["packages"].items() if k != "detail"
                    }
                },
                "stages": {
                    k: {key: v.get(key) for key in ("status", "findings")}
                    for k, v in stages.items()
                },
                "work_packages": sorted(state["packages"]),
                "requirements": list(kravspec.get("requirements") or []),
            },
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=f"{state['milestone_id']}:{head[:12]}:release",
            prompt_version=RELEASE_MANAGER_PROMPT.ref,
        )
        known = {str(r.get("id")) for r in kravspec.get("requirements") or []} | set(
            state["packages"]
        )
        mentioned = set(_ID_IN_TEXT.findall(value["release_notes"]))
        invented = sorted(m for m in mentioned if m not in known)
        checklist_holds = all(i["holds"] for i in checklist)
        problems = []
        if invented:
            problems.append(f"release notes name ids that do not exist: {invented}")
        if value["recommendation"] == "ready" and not checklist_holds:
            problems.append("recommends ready although the checklist does not hold")
        return {
            # The recommendation goes to the board; it is not a decision.
            "status": "failed" if problems else "passed",
            "reason": "; ".join(problems) or None,
            "recommendation": value["recommendation"],
            "release_notes": value["release_notes"],
            "reasons": list(value.get("reasons") or []),
            "risks": list(value.get("risks") or []),
            "agent_jobs": [turn.job()],
        }

    # ----------------------------------------------------------------- #
    def approve(self, milestone_id: str, *, approver: str) -> dict[str, Any]:
        """The project manager's approval: the milestone may go to ``main`` as one PR."""
        if not approver:
            raise MilestoneError("approval needs the project manager")
        state = self._store.get(milestone_id)
        if state["status"] != "awaiting_approval":
            raise MilestoneError("the milestone is not awaiting approval")
        head = self._top(state)
        if head != state["milestone_review"]["head_sha"]:
            raise MilestoneError("the milestone branch moved after its review")
        if not self._workspaces.is_ancestor(self._main(), head):
            raise MilestoneError(
                "main moved after the review; finish the milestone again"
            )
        state.update(status="approved", approved_by=approver, approved_head_sha=head)
        _event(state, "milestone_approved", approver, head_sha=head)
        return self._store.put(state)

    def mark_merged(
        self,
        milestone_id: str,
        *,
        main_sha: str,
        actor: str,
        backup_dir: str | Path,
        backup_state: Callable[[Path], Sequence[Path]] | None = None,
    ) -> dict[str, Any]:
        """After the PR is merged: tag known-good, back up, delete the branch."""
        state = self._store.get(milestone_id)
        if state["status"] != "approved":
            raise MilestoneError("only an approved milestone can be marked merged")
        if self._workspaces.resolve(
            main_sha
        ) != main_sha or not self._workspaces.is_ancestor(
            state["approved_head_sha"], main_sha
        ):
            raise MilestoneError("main does not contain the approved milestone")
        tag = f"refs/tags/known-good/{milestone_id}"
        self._workspaces.update_ref(tag, main_sha, None)
        target = Path(backup_dir) / milestone_id
        bundle = self._workspaces.bundle(
            target / f"{milestone_id}-{main_sha[:12]}.bundle"
        )
        state_copy = target / f"{milestone_id}-state.json"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._store.path(milestone_id), state_copy)
        extra = [str(p) for p in (backup_state(target) if backup_state else ())]
        evidence = {
            "milestone_id": milestone_id,
            "tag": tag,
            "main_sha": main_sha,
            "approved_by": state["approved_by"],
            "approved_head_sha": state["approved_head_sha"],
            "milestone_review": {
                k: v
                for k, v in state["milestone_review"].items()
                if k not in {"suite", "statistics", "agent_jobs"}
            },
            "release": (state["milestone_review"].get("stages") or {}).get("release"),
            "statistics": state["milestone_review"].get("statistics"),
            "bundle": str(bundle),
            "state_backup": [str(state_copy), *extra],
        }
        (target / f"{milestone_id}-release-evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
        )
        branch = f"refs/heads/{state['branch']}"
        branch_sha = self._workspaces.resolve(branch)
        if branch_sha:
            self._workspaces.delete_ref(branch, branch_sha)
        state.update(
            status="merged",
            known_good_tag=tag,
            merged_main_sha=main_sha,
            backup=evidence,
        )
        _event(state, "milestone_merged", actor, main_sha=main_sha, tag=tag)
        return self._store.put(state)

    # ----------------------------------------------------------------- #
    @staticmethod
    def _require_running(state: Mapping[str, Any]) -> None:
        if state["status"] != "running":
            raise MilestoneError(f"milestone is {state['status']}, not running")

    @staticmethod
    def _current_sprint(state: Mapping[str, Any]) -> dict[str, Any] | None:
        return state["sprints"][-1] if state["sprints"] else None


def record_plan(state: Mapping[str, Any], sprint: int) -> list[str]:
    """The sprint's packages that still need doing (merged ones are not run again)."""
    planned = next(s for s in state["sprint_plan"] if s["sprint"] == sprint)
    return [
        t for t in planned["packages"] if state["packages"][t]["status"] != "merged"
    ]


def restore_known_good(
    workspaces: FactoryWorkspaceManager, milestone_id: str, *, branch: str
) -> str:
    """Roll back: a new branch from the known-good tag; history is never rewritten."""
    sha = workspaces.resolve(f"refs/tags/known-good/{milestone_id}")
    if not sha:
        raise MilestoneError(f"no known-good tag for {milestone_id}")
    if not branch.startswith("rollback/"):
        raise MilestoneError("a rollback branch is named rollback/<name>")
    workspaces.update_ref(f"refs/heads/{branch}", sha, None)
    return sha


# --------------------------------------------------------------------- #
# Command line: the git-only steps of a milestone, by hand
# --------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Milestone branch operations (DOR step 8)."
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--milestone", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    review = sub.add_parser("review-sprint")
    review.add_argument("--sprint", type=int, required=True)
    review.add_argument("--decision", choices=SPRINT_DECISIONS, required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", default="")
    approve = sub.add_parser("approve")
    approve.add_argument("--approver", required=True)
    merged = sub.add_parser("mark-merged")
    merged.add_argument("--main-sha", required=True)
    merged.add_argument("--actor", required=True)
    merged.add_argument(
        "--backup-dir", default=os.getenv("DOR_BACKUP_DIR", "./var/backup")
    )
    rollback = sub.add_parser("rollback")
    rollback.add_argument("--branch", required=True)
    args = parser.parse_args(argv)

    workspaces = FactoryWorkspaceManager(args.repo)
    store = FileMilestoneStore.from_environment()
    runner = MilestoneRunner(workspaces, None, None, store)  # type: ignore[arg-type]
    try:
        if args.command == "show":
            state = store.get(args.milestone)
        elif args.command == "review-sprint":
            state = runner.review_sprint(
                args.milestone,
                args.sprint,
                args.decision,
                reviewer=args.reviewer,
                note=args.note,
            )
        elif args.command == "approve":
            state = runner.approve(args.milestone, approver=args.approver)
        elif args.command == "mark-merged":
            state = runner.mark_merged(
                args.milestone,
                main_sha=args.main_sha,
                actor=args.actor,
                backup_dir=args.backup_dir,
            )
        else:
            print(restore_known_good(workspaces, args.milestone, branch=args.branch))
            return 0
    except (MilestoneError, FactoryWorkspaceError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
