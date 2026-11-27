"""Completion plan step 7: control of a delivered work package.

A delivery from the coder (step 6) passes three controls, in order:

1. **Fact check** (system, no language model). References in the delivery
   must exist; every acceptance criterion of the package needs a test that
   names it; the write scope is checked again; the factory runs the tests
   itself, because a test counts only when the system has run it.
2. **Level 1, technical** (code auditor). Diff, house rules and the fact
   check's test results; findings must point at a changed file and an
   existing line.
3. **Level 2, requirements and architecture** (context controller). Diff,
   requirements, acceptance criteria and the module contract; runs only after
   level 1 passed and cannot overturn a technical failure. Every finding says
   whether its cause is the ``code`` or the ``input`` (contract, kravspec or
   assumption).

Both control roles come from a different producer than the coder and get a
fixed context packet: never the coder's conversation or explanation. If no
independent producer is available, the control waits; it never falls back
to the coder's producer (decision 36).

:class:`PackageLine` drives one package to an outcome with the fixed
sorting from "Tilbagerulning frem for fejlretning" (decision 7 and 35): a
local, understood failure goes back to the coder at most twice; then the
package is discarded and built again by a fresh agent; if that fails too, it
goes to the human. A cause in the input stops the line and goes to the
change process. Every decision and its reason is recorded with the
measurements the agent statistics need.
"""

from __future__ import annotations

import copy
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from domain.factory_work import WriteScope
from domain.role_process import (
    RoleAssignment,
    RoleCatalog,
    RoleProcessError,
    default_catalog,
    validate_assignment,
)
from execution.role_dialogue import REVIEW_SCHEMA, call_role, fingerprint
from execution.task_compiler import CONTRACT_ROOT
from execution.worker_adapter import (
    CODER_ROLE,
    HOUSE_RULES_VERSION,
    WorkerAdapter,
    WorkerResult,
    active_house_rules,
)
from services.bot_llm_runtime import BoundModel
from services.factory_workspace import FactoryWorkspaceError, FactoryWorkspaceManager

CODE_AUDITOR_ROLE = "code_auditor"
CONTEXT_CONTROLLER_ROLE = "context_controller"
CONTROL_FORMAT_VERSION = "dor-control-v1"
MAX_REWORK_ROUNDS = 2
OUTPUT_LIMIT = 8_000

#: An acceptance-criterion id as it appears in code, test names and docs
#: (``AC-REG-01-1`` or ``ac_reg_01_1``).
CRITERION_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])AC[-_][A-Z]+[-_]\d+[-_]\d+(?!\d)", re.IGNORECASE
)
_TEST_NAME = re.compile(r"(^test_|_test\.|\.test\.|\.spec\.|^conftest\.py$)")
_ASSUMPTION_LINE = re.compile(r"^\s*(?:[-*]|\d+[.)])\s+\S")

LEVEL1_SCHEMA: dict[str, Any] = REVIEW_SCHEMA

LEVEL2_SCHEMA: dict[str, Any] = copy.deepcopy(REVIEW_SCHEMA)
_level2_item = LEVEL2_SCHEMA["properties"]["findings"]["items"]
_level2_item["properties"]["cause"] = {"type": "string", "enum": ["code", "input"]}
_level2_item["required"] = [*_level2_item["required"], "cause"]

LEVEL1_INSTRUCTIONS = """You are the code auditor (level 1, technical) in a governed software factory.
You review a coder's delivery from a different producer than the coder. You see only the diff,
the house rules, the project rules and the factory's own check results; you never see the coder's
conversation, and the coder's claims are not evidence.
Hold the code up against the house rules and the project rules. Judge correctness, error handling,
security, tests that actually test the criterion they name, and code that does more than the package asks.
Return verdict "approve" or "revise" and findings. Every finding must point at a changed file as
"path" or "path:line" (a line that exists in the delivered file), give severity
blocking/major/minor, describe the issue precisely and list affected requirement ids (may be empty).
Findings that do not point at something real are rejected by the fact check."""

LEVEL2_INSTRUCTIONS = """You are the context controller (level 2, requirements and architecture) in a governed
software factory, from a different producer than the coder. The delivery has passed the technical level.
You see the diff, the requirements, the acceptance criteria, the module contract and the factory's own test
results; never the coder's conversation.
Judge whether the delivery does exactly what the requirements and the contract ask: every acceptance
criterion fulfilled as written, interfaces as in the contract, nothing missing and nothing unrequested.
Return verdict "approve" or "revise" and findings. Every finding points at a changed file ("path" or
"path:line"), an acceptance criterion id or a requirement id of this package, gives severity, the issue,
the affected requirement ids, and a cause: "code" if the delivery is wrong against a sound input, "input" if
the requirement, the contract or a marked assumption is wrong, contradictory or missing, so that no correct
code could satisfy it."""


class PackageControlError(RuntimeError):
    """The control cannot produce a trustworthy result."""


def _truncate(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else "...\n" + text[-OUTPUT_LIMIT:]


def criterion_ref(text: str) -> str:
    return text.upper().replace("_", "-")


def is_test_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return bool(_TEST_NAME.search(pure.name)) or bool(
        {"tests", "test", "__tests__"} & set(pure.parts[:-1])
    )


# --------------------------------------------------------------------- #
# The factory's own test runs
# --------------------------------------------------------------------- #
@dataclass(frozen=True)
class CheckRequest:
    """What the factory runs on a checked-out delivery."""

    task_type: str
    test_files: tuple[str, ...]
    source_files: tuple[str, ...]


CheckRunner = Callable[[Path, CheckRequest], list[dict[str, Any]]]


def _check_environment(home: str) -> dict[str, str]:
    """No credentials reach code the factory did not write."""
    env = {
        name: os.environ[name]
        for name in ("PATH", "LANG", "LC_ALL", "TZ")
        if name in os.environ
    }
    env.update(HOME=home, PYTHONDONTWRITEBYTECODE="1", GIT_TERMINAL_PROMPT="0")
    return env


def _run(name: str, command: list[str], cwd: Path, timeout: int) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="dor-check-home-") as home:
        try:
            done = subprocess.run(
                command,
                cwd=cwd,
                env=_check_environment(home),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "name": name,
                "status": "failed",
                "command": command,
                "exit_code": None,
                "output": _truncate(f"timed out after {timeout} s\n{exc.stdout or ''}"),
            }
    return {
        "name": name,
        "status": "passed" if done.returncode == 0 else "failed",
        "command": command,
        "exit_code": done.returncode,
        "output": _truncate((done.stdout or "") + (done.stderr or "")),
    }


def run_python_checks(
    path: Path, request: CheckRequest, *, timeout: int = 900
) -> list[dict[str, Any]]:
    """Run the delivery's Python tests (and ruff, when installed) in ``path``.

    The contract foundation writes contract tests that must fail until the
    modules exist, so for it the tests only have to be collectable.
    """
    python_tests = [f for f in request.test_files if f.endswith(".py")]
    results: list[dict[str, Any]] = []
    if not python_tests:
        results.append(
            {
                "name": "tests",
                "status": "not_available",
                "command": [],
                "exit_code": None,
                "output": "no Python test files to run",
            }
        )
    else:
        collect = request.task_type == "contract_foundation"
        results.append(
            _run(
                "tests",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    *(["--collect-only"] if collect else []),
                    *python_tests,
                ],
                path,
                timeout,
            )
        )
    sources = [f for f in request.source_files if f.endswith(".py")]
    ruff = _which("ruff")
    if sources and ruff:
        results.append(
            _run("lint", [ruff, "check", "--no-cache", *sources], path, timeout)
        )
    else:
        results.append(
            {
                "name": "lint",
                "status": "not_available",
                "command": [],
                "exit_code": None,
                "output": "no Python sources"
                if not sources
                else "ruff is not installed",
            }
        )
    return results


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


# --------------------------------------------------------------------- #
# Fact check
# --------------------------------------------------------------------- #
def fact_check(
    workspaces: FactoryWorkspaceManager,
    delivery: WorkerResult,
    package: Mapping[str, Any],
    contracts: Mapping[str, Any],
    *,
    base_sha: str,
    runner: CheckRunner = run_python_checks,
) -> dict[str, Any]:
    """The deterministic control of a delivery. No language model."""
    head = str(delivery.head_sha)
    findings: list[dict[str, Any]] = []

    def finding(code: str, target: str, issue: str) -> None:
        findings.append(
            {
                "id": f"FC-{len(findings) + 1}",
                "code": code,
                "target": target,
                "issue": issue,
            }
        )

    scope = WriteScope(
        tuple(package["write_scope"]["allowed_paths"]),
        tuple(package["write_scope"].get("denied_paths") or ()),
    )
    try:
        affected = workspaces.changed_paths(base_sha, head, scope)
    except FactoryWorkspaceError as exc:
        affected = workspaces.changed_paths(base_sha, head)
        finding("out_of_scope", "write_scope", str(exc))

    known = {str(c["id"]).upper() for c in contracts.get("acceptance_criteria") or []}
    criteria = {str(c).upper() for c in package.get("criterion_ids") or []}
    contents = {
        p: text for p in affected if (text := workspaces.read_file(head, p)) is not None
    }
    tested: dict[str, set[str]] = {}
    invented = 0
    for path, text in contents.items():
        for number, line in enumerate(text.splitlines(), 1):
            for match in CRITERION_PATTERN.finditer(line):
                ref = criterion_ref(match.group(0))
                if ref not in known:
                    invented += 1
                    finding(
                        "invented_reference",
                        f"{path}:{number}",
                        f"{ref} (written {match.group(0)!r}) is not an acceptance criterion of the project",
                    )
                elif is_test_path(path):
                    tested.setdefault(ref, set()).add(path)

    # Contract tests from the foundation for this module's criteria count too.
    contract_tests: list[str] = []
    if package.get("task_type") != "contract_foundation":
        for path in workspaces.list_files(head, CONTRACT_ROOT):
            if not is_test_path(path):
                continue
            text = workspaces.read_file(head, path) or ""
            refs = {criterion_ref(m.group(0)) for m in CRITERION_PATTERN.finditer(text)}
            if refs & criteria:
                contract_tests.append(path)
                for ref in refs & criteria:
                    tested.setdefault(ref, set()).add(path)

    for criterion in sorted(criteria - set(tested)):
        finding(
            "criterion_without_test",
            criterion,
            f"no test in the delivery names {criterion}",
        )

    test_files = tuple(
        sorted({*(p for p in contents if is_test_path(p)), *contract_tests})
    )
    source_files = tuple(sorted(p for p in contents if not is_test_path(p)))
    if not test_files:
        finding("no_tests", "delivery", "the delivery contains no tests")
        checks: list[dict[str, Any]] = []
    else:
        with workspaces.checkout(head) as path:
            checks = runner(
                path,
                CheckRequest(str(package.get("task_type")), test_files, source_files),
            )
        for check in checks:
            if check["status"] == "failed":
                finding(
                    f"{check['name']}_failed",
                    check["name"],
                    f"the factory's own {check['name']} run failed (exit {check['exit_code']})",
                )
        tests_passed = any(
            c["name"] == "tests" and c["status"] == "passed" for c in checks
        )
        if not tests_passed and not any(f["code"] == "tests_failed" for f in findings):
            finding(
                "tests_not_run",
                "tests",
                "the factory could not run the delivery's tests; a test counts only when the system ran it",
            )

    assumptions = sum(
        1
        for path, text in contents.items()
        if PurePosixPath(path).name == "ASSUMPTIONS.md"
        for line in text.splitlines()
        if _ASSUMPTION_LINE.match(line)
    )
    return {
        "findings": findings,
        "checks": checks,
        "affected_paths": list(affected),
        "test_files": list(test_files),
        "criteria_tested": {k: sorted(v) for k, v in sorted(tested.items())},
        "measurements": {
            "invented_references": invented,
            "out_of_scope_changes": sum(
                1 for f in findings if f["code"] == "out_of_scope"
            ),
            "assumptions": assumptions,
        },
    }


# --------------------------------------------------------------------- #
# Reviewer fact check (rule 5: findings point at a file and line)
# --------------------------------------------------------------------- #
def verify_findings(
    review: Mapping[str, Any],
    *,
    files: Mapping[str, str],
    other_targets: set[str],
    requirement_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    verified, rejected = [], []
    for item in review.get("findings") or []:
        target = str(item.get("target") or "")
        problems = []
        path, _, line = target.rpartition(":") if ":" in target else (target, "", "")
        if target in other_targets:
            pass
        elif path in files and line.isdigit():
            if not 1 <= int(line) <= max(1, len(files[path].splitlines())):
                problems.append(f"line {line} does not exist in {path}")
        elif target in files:
            pass
        else:
            problems.append(f"unknown target {target!r}")
        unknown = [
            r for r in item.get("requirement_ids") or [] if r not in requirement_ids
        ]
        if unknown:
            problems.append(f"unknown requirements {unknown}")
        entry = dict(item)
        if problems:
            entry["rejected_because"] = problems
            rejected.append(entry)
        else:
            verified.append(entry)
    return verified, rejected


# --------------------------------------------------------------------- #
# The control of one delivery
# --------------------------------------------------------------------- #
class PackageControl:
    """Fact check, level 1 and level 2 on one delivery (completion plan step 7)."""

    def __init__(
        self,
        workspaces: FactoryWorkspaceManager,
        auditor: BoundModel,
        controller: BoundModel,
        *,
        catalog: RoleCatalog | None = None,
        runner: CheckRunner = run_python_checks,
        house_rules: list[dict[str, str]] | None = None,
        project_rules: Sequence[Mapping[str, Any]] = (),
    ) -> None:
        self._workspaces = workspaces
        self._auditor = auditor
        self._controller = controller
        self._catalog = catalog or default_catalog()
        self._runner = runner
        self._house_rules = house_rules
        self._project_rules = [dict(r) for r in project_rules]

    def independence_problem(
        self, package_id: str, coder_brand: str, coder_session: str, run_key: str
    ) -> str | None:
        """Why the controls cannot run now, or ``None``."""
        coder = RoleAssignment(
            "coder", package_id, CODER_ROLE, coder_brand, coder_session
        )
        try:
            for role, model in (
                (CODE_AUDITOR_ROLE, self._auditor),
                (CONTEXT_CONTROLLER_ROLE, self._controller),
            ):
                validate_assignment(
                    self._catalog,
                    RoleAssignment(
                        role,
                        package_id,
                        role,
                        model.identity.brand,
                        f"{run_key}:{role}",
                    ),
                    [coder],
                )
        except RoleProcessError as exc:
            return str(exc)
        return None

    def check(
        self,
        delivery: WorkerResult,
        package: Mapping[str, Any],
        contracts: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        *,
        base_sha: str,
        organization_id: str,
        actor_id: str,
        run_key: str,
        architecture: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if delivery.status != "delivered" or not delivery.head_sha:
            raise PackageControlError("only a delivered package can be controlled")
        package_id = str(package["logical_task_id"])
        coder_job = delivery.agent_job
        waiting = self.independence_problem(
            package_id,
            str(coder_job["agent"]["brand"]),
            str(coder_job["session_id"]),
            run_key,
        )
        if waiting:
            return {
                "status": "waiting",
                "stage": "independence",
                "reason": waiting,
                "findings": [],
                "agent_jobs": [],
            }

        result: dict[str, Any] = {
            "control_format": CONTROL_FORMAT_VERSION,
            "head_sha": delivery.head_sha,
            "agent_jobs": [],
            "level1": None,
            "level2": None,
        }
        facts = fact_check(
            self._workspaces,
            delivery,
            package,
            contracts,
            base_sha=base_sha,
            runner=self._runner,
        )
        result["fact_check"] = facts
        if facts["findings"]:
            return {
                **result,
                "status": "failed",
                "stage": "fact_check",
                "cause": "code",
                "findings": [
                    {
                        **f,
                        "severity": "blocking",
                        "requirement_ids": [],
                        "source": "fact_check",
                    }
                    for f in facts["findings"]
                ],
            }

        head = str(delivery.head_sha)
        files = {
            p: text
            for p in facts["affected_paths"]
            if (text := self._workspaces.read_file(head, p)) is not None
        }
        diff = self._workspaces.diff(base_sha, head)
        requirement_ids = {str(r) for r in package.get("requirement_ids") or []}
        all_requirement_ids = {
            str(r.get("id")) for r in kravspec.get("requirements") or []
        }
        test_results = {
            "checks": facts["checks"],
            "criteria_tested": facts["criteria_tested"],
        }
        work_package = {
            "logical_task_id": package_id,
            "task_type": package.get("task_type"),
            "module_id": package.get("module_id"),
            "requirement_ids": sorted(requirement_ids),
            "criterion_ids": list(package.get("criterion_ids") or []),
        }

        level1 = self._review(
            result,
            CODE_AUDITOR_ROLE,
            self._auditor,
            LEVEL1_INSTRUCTIONS,
            LEVEL1_SCHEMA,
            {
                "control_format": CONTROL_FORMAT_VERSION,
                "work_package": work_package,
                "diff": diff,
                "house_rules": {
                    "version": HOUSE_RULES_VERSION,
                    "active": self._house_rules
                    if self._house_rules is not None
                    else active_house_rules(),
                },
                "project_rules": self._project_rules,
                "factory_test_results": test_results,
            },
            files=files,
            other_targets=set(),
            requirement_ids=all_requirement_ids,
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=run_key,
        )
        if level1["open_findings"]:
            return {
                **result,
                "status": "failed",
                "stage": "level1",
                "cause": "code",
                "findings": [{**f, "cause": "code"} for f in level1["open_findings"]],
            }

        criteria = {str(c["id"]): c for c in contracts.get("acceptance_criteria") or []}
        module_id = package.get("module_id")
        level2 = self._review(
            result,
            CONTEXT_CONTROLLER_ROLE,
            self._controller,
            LEVEL2_INSTRUCTIONS,
            LEVEL2_SCHEMA,
            {
                "control_format": CONTROL_FORMAT_VERSION,
                "work_package": work_package,
                "diff": diff,
                "requirements": [
                    r
                    for r in kravspec.get("requirements") or []
                    if str(r.get("id")) in requirement_ids
                ],
                "acceptance_criteria": [
                    criteria[c] for c in work_package["criterion_ids"] if c in criteria
                ],
                "contracts": [
                    m
                    for m in contracts.get("modules") or []
                    if package.get("task_type") == "contract_foundation"
                    or m.get("module_id") == module_id
                ],
                "approved_architecture": dict(architecture or {}),
                "factory_test_results": test_results,
            },
            files=files,
            other_targets={*work_package["criterion_ids"], *requirement_ids},
            requirement_ids=all_requirement_ids,
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=run_key,
        )
        if level2["open_findings"]:
            causes = {f.get("cause") for f in level2["open_findings"]}
            return {
                **result,
                "status": "failed",
                "stage": "level2",
                "cause": "input" if "input" in causes else "code",
                "findings": level2["open_findings"],
            }
        return {**result, "status": "passed", "stage": "level2", "findings": []}

    def _review(
        self,
        result: dict[str, Any],
        role: str,
        model: BoundModel,
        instructions: str,
        schema: Mapping[str, Any],
        packet: Mapping[str, Any],
        *,
        files: Mapping[str, str],
        other_targets: set[str],
        requirement_ids: set[str],
        organization_id: str,
        actor_id: str,
        run_key: str,
    ) -> dict[str, Any]:
        review, turn = call_role(
            model,
            purpose=f"package_control:{role}",
            role=role,
            round_number=1,
            instructions=instructions,
            schema=schema,
            context_packet=packet,
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=run_key,
        )
        result["agent_jobs"].append(turn.job())
        verified, rejected = verify_findings(
            review,
            files=files,
            other_targets=other_targets,
            requirement_ids=requirement_ids,
        )
        open_findings = [
            {**f, "source": role}
            for f in verified
            if f["severity"] in {"blocking", "major"}
        ]
        level = {
            "role": role,
            "verdict": review.get("verdict"),
            "packet_fingerprint": fingerprint(packet),
            "findings": verified,
            "rejected_findings": rejected,
            "open_findings": open_findings,
            # A "revise" verdict without a verifiable finding is recorded, not obeyed.
            "unsupported_verdict": review.get("verdict") == "revise"
            and not open_findings,
            "passed": not open_findings,
        }
        result["level1" if role == CODE_AUDITOR_ROLE else "level2"] = level
        return level


# --------------------------------------------------------------------- #
# Sorting: rework, discard and rebuild, change of input, human
# --------------------------------------------------------------------- #
def triage(
    control: Mapping[str, Any] | None,
    *,
    worker_failed: bool,
    generation: int,
    rework_rounds: int,
    max_rework: int = MAX_REWORK_ROUNDS,
) -> str:
    """The fixed sorting from "Tilbagerulning frem for fejlretning"."""
    if worker_failed:
        # Not understood: discard and build again with a fresh agent, once.
        return "regenerate" if generation == 1 else "escalate"
    assert control is not None
    if control["status"] == "passed":
        return "passed"
    if control["status"] == "waiting":
        return "waiting"
    if control.get("cause") == "input":
        return "change_input"
    if generation == 1 and rework_rounds < max_rework:
        return "rework"
    return "regenerate" if generation == 1 else "escalate"


@dataclass(frozen=True)
class AgentChoice:
    """A coding agent for one generation of a package."""

    agent: str
    api_key: str | None
    model: str | None = None


class PackageLine:
    """Drive one work package from coder to a controlled outcome."""

    def __init__(
        self,
        adapter: WorkerAdapter,
        control: PackageControl,
        workspaces: FactoryWorkspaceManager,
        *,
        max_rework: int = MAX_REWORK_ROUNDS,
    ) -> None:
        if max_rework < 0:
            raise ValueError("max_rework must be >= 0")
        self._adapter = adapter
        self._control = control
        self._workspaces = workspaces
        self._max_rework = max_rework

    def deliver(
        self,
        package: Mapping[str, Any],
        contracts: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        *,
        coder: AgentChoice,
        base_sha: str,
        execution_id: str,
        organization_id: str,
        actor_id: str,
        fresh_coder: AgentChoice | None = None,
        architecture: Mapping[str, Any] | None = None,
        timeout_seconds: int = 3600,
        run_id: str = "",
    ) -> dict[str, Any]:
        """``run_id`` names this run of the package (a sprint run, a rebuild): model
        calls are idempotent per run, so a new run must not reuse an old one's keys."""
        task_id = str(package["logical_task_id"])
        attempts: list[dict[str, Any]] = []
        agent_jobs: list[dict[str, Any]] = []
        superseded: list[str] = []
        generation, rework_rounds, attempt = 1, 0, 0
        start_sha: str | None = None
        findings: list[dict[str, Any]] | None = None
        final: WorkerResult | None = None

        while True:
            attempt += 1
            choice = coder if generation == 1 else (fresh_coder or coder)
            kind = (
                "initial" if attempt == 1 else ("rework" if start_sha else "regenerate")
            )
            result = self._adapter.run(
                package,
                contracts,
                kravspec,
                agent=choice.agent,
                base_sha=base_sha,
                execution_id=execution_id,
                api_key=choice.api_key,
                model=choice.model,
                timeout_seconds=timeout_seconds,
                attempt=attempt,
                start_sha=start_sha,
                rework_findings=findings,
            )
            agent_jobs.append(result.agent_job)
            control = None
            if result.status == "delivered":
                control = self._control.check(
                    result,
                    package,
                    contracts,
                    kravspec,
                    base_sha=base_sha,
                    organization_id=organization_id,
                    actor_id=actor_id,
                    run_key=f"{execution_id}:{run_id or base_sha[:12]}:{task_id}:a{attempt}:control",
                    architecture=architecture,
                )
                agent_jobs.extend(control.get("agent_jobs") or [])
            decision = triage(
                control,
                worker_failed=result.status != "delivered",
                generation=generation,
                rework_rounds=rework_rounds,
                max_rework=self._max_rework,
            )
            attempts.append(
                {
                    "attempt": attempt,
                    "generation": generation,
                    "kind": kind,
                    "agent": choice.agent,
                    "worker": {
                        "status": result.status,
                        "reason": result.reason,
                        "branch": result.branch,
                        "head_sha": result.head_sha,
                        "log_reference": result.log_reference,
                    },
                    "control": _control_summary(control),
                    "decision": decision,
                    "reason": _reason(result, control, decision),
                }
            )
            if decision == "rework":
                rework_rounds += 1
                start_sha = result.head_sha
                findings = list(control["findings"]) if control else []
                superseded.append(str(result.branch))
                continue
            if decision == "regenerate":
                generation, rework_rounds, start_sha, findings = 2, 0, None, None
                if result.branch:
                    superseded.append(result.branch)
                continue
            final = result
            break

        keep = final.branch if decision in {"passed", "waiting"} else None
        for branch in {*superseded, *([final.branch] if final.branch else [])}:
            if branch and branch != keep:
                self._workspaces.discard_branch(branch)
        status = {"escalate": "escalated"}.get(decision, decision)
        return {
            "status": status,
            "work_package": task_id,
            "branch": keep,
            "head_sha": final.head_sha if keep else None,
            "base_sha": base_sha,
            # What a later recheck needs: the delivery that was kept.
            "delivery": {
                "affected_paths": list(final.affected_paths),
                "log_reference": final.log_reference,
                "coder_job": final.agent_job,
            }
            if keep
            else None,
            "reason": attempts[-1]["reason"],
            "attempts": attempts,
            "agent_jobs": agent_jobs,
            "measurements": _measurements(attempts),
        }


def _control_summary(control: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if control is None:
        return None
    facts = control.get("fact_check") or {}
    return {
        "status": control["status"],
        "stage": control.get("stage"),
        "cause": control.get("cause"),
        "reason": control.get("reason"),
        "findings": list(control.get("findings") or []),
        "checks": [
            {k: c.get(k) for k in ("name", "status", "exit_code")}
            for c in facts.get("checks") or []
        ],
        "fact_check_measurements": dict(facts.get("measurements") or {}),
        "level1_passed": (control.get("level1") or {}).get("passed"),
        "level2_passed": (control.get("level2") or {}).get("passed"),
        "rejected_reviewer_findings": sum(
            len((control.get(level) or {}).get("rejected_findings") or [])
            for level in ("level1", "level2")
        ),
        "unsupported_verdicts": sum(
            1
            for level in ("level1", "level2")
            if (control.get(level) or {}).get("unsupported_verdict")
        ),
    }


def _reason(
    result: WorkerResult, control: Mapping[str, Any] | None, decision: str
) -> str:
    if result.status != "delivered":
        return f"worker: {result.reason}"
    assert control is not None
    if control["status"] == "waiting":
        return f"control waits: {control.get('reason')}"
    if control["status"] == "passed":
        return "fact check, level 1 and level 2 passed"
    codes = sorted(
        {str(f.get("code") or f.get("id")) for f in control.get("findings") or []}
    )
    return f"{control.get('stage')} failed ({control.get('cause')}): {', '.join(codes)}"


def _measurements(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    controls = [a["control"] for a in attempts if a["control"]]
    first = next((c for c in controls if c["status"] != "waiting"), None)

    def first_try(level: str) -> bool | None:
        """Did the first controlled delivery pass ``level``? Not reached is not passed."""
        if first is None:
            return None
        return bool(first[f"{level}_passed"])

    final = controls[-1] if controls else None
    return {
        "fact_check_passed_first_try": None
        if first is None
        else first["stage"] != "fact_check",
        "level1_passed_first_try": first_try("level1"),
        "level2_passed_first_try": first_try("level2"),
        "invented_references": sum(
            c["fact_check_measurements"].get("invented_references", 0) for c in controls
        ),
        "out_of_scope_changes": sum(
            1
            for a in attempts
            if str(a["worker"]["reason"] or "").startswith("write scope violated")
        )
        + sum(
            c["fact_check_measurements"].get("out_of_scope_changes", 0)
            for c in controls
        ),
        "rework_rounds": sum(1 for a in attempts if a["decision"] == "rework"),
        "discarded_attempts": sum(1 for a in attempts if a["decision"] == "regenerate"),
        "assumptions": (final or {})
        .get("fact_check_measurements", {})
        .get("assumptions", 0)
        if final and final["status"] == "passed"
        else None,
        "rejected_reviewer_findings": sum(
            c["rejected_reviewer_findings"] for c in controls
        ),
        "unsupported_verdicts": sum(c["unsupported_verdicts"] for c in controls),
    }


# --------------------------------------------------------------------- #
# Configuration from the Bot Catalog
# --------------------------------------------------------------------- #
class PackageControlConfigurationError(RuntimeError):
    pass


def default_package_control(
    organization_id: str, workspaces: FactoryWorkspaceManager
) -> PackageControl | None:
    """Build the controls from configured Bot Catalog profiles.

    ``DOR_CODE_AUDITOR_BOT_PROFILE`` and ``DOR_CONTEXT_CONTROLLER_BOT_PROFILE``
    name the two control roles. Neither set: no controls configured (a
    delivery is then not controlled and cannot pass). Only one set: fail
    closed. Independence from the coder is checked per delivery.
    """
    auditor = os.getenv("DOR_CODE_AUDITOR_BOT_PROFILE", "").strip()
    controller = os.getenv("DOR_CONTEXT_CONTROLLER_BOT_PROFILE", "").strip()
    if not auditor and not controller:
        return None
    if not auditor or not controller:
        raise PackageControlConfigurationError(
            "DOR_CODE_AUDITOR_BOT_PROFILE and DOR_CONTEXT_CONTROLLER_BOT_PROFILE "
            "must both be set for the package controls"
        )
    from api.dependencies import resolve_bot_model_for

    return PackageControl(
        workspaces,
        resolve_bot_model_for(organization_id, auditor),
        resolve_bot_model_for(organization_id, controller),
    )
