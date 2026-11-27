"""The first end-to-end run (completion plan step 8a), by hand.

``config/first_run/factory.yaml`` says which producer holds which role.
This command line checks that assignment against the role catalog, creates
the Bot Catalog entries through the DOR API (keys are read from the
operator's environment and stored encrypted; they are never printed), and
drives the milestone from an approved pipeline status: start, one sprint at
a time, finish. Approval and merge stay with the project board
(``python -m execution.milestone approve`` / ``mark-merged``).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from domain.role_process import RoleCatalog, RoleKind, default_catalog

CONFIG_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "first_run" / "factory.yaml"
)
#: Roles that judge the whole milestone and must be independent of every builder.
MILESTONE_JUDGES = (
    "context_controller",
    "system_architect",
    "product_owner",
    "release_manager",
    "code_auditor",
    "security_reviewer",
)
BUILDERS = ("test_designer", "coder")


class FirstRunError(RuntimeError):
    pass


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def role_brands(config: Mapping[str, Any]) -> dict[str, str]:
    connections = {c["connection_id"]: c for c in config["connections"]}
    deployments = {d["deployment_id"]: d for d in config["deployments"]}
    brands: dict[str, str] = {}
    for profile in config["profiles"]:
        deployment = deployments.get(profile["deployment_id"])
        if deployment is None:
            raise FirstRunError(
                f"{profile['bot_profile_id']}: unknown deployment {profile['deployment_id']}"
            )
        connection = connections.get(deployment["connection_id"])
        if connection is None:
            raise FirstRunError(
                f"{deployment['deployment_id']}: unknown connection {deployment['connection_id']}"
            )
        brands[profile["role"]] = connection["brand"]
    for role, agent in config["agents"].items():
        brands[role] = agent["brand"]
    return brands


#: Control relations that actually run in the first run: (controller, controlled).
#: Other catalog relations between assigned roles are reported as warnings.
EXERCISED = {
    ("architecture_reviewer", "architect"),
    ("context_controller", "contract_author"),
    ("system_architect", "task_producer"),
    *(
        (judge, builder)
        for judge in ("code_auditor", "security_reviewer", "context_controller")
        for builder in BUILDERS
    ),
    ("test_designer", "coder"),
}


def check_config(
    config: Mapping[str, Any], catalog: RoleCatalog | None = None
) -> list[str]:
    """Problems with the role assignment; empty means the first run can go."""
    return assignment_report(config, catalog)["problems"]


def assignment_report(
    config: Mapping[str, Any], catalog: RoleCatalog | None = None
) -> dict[str, list[str]]:
    """``problems`` block the run; ``warnings`` are catalog relations between
    roles on the same producer that the first run does not exercise."""
    catalog = catalog or default_catalog()
    problems: list[str] = []
    warnings: list[str] = []
    try:
        brands = role_brands(config)
    except FirstRunError as exc:
        return {"problems": [str(exc)], "warnings": []}
    for role in brands:
        if role not in catalog.roles:
            problems.append(f"{role} is not a role in the catalog")
        elif catalog.role(role).kind is not RoleKind.AGENT:
            problems.append(f"{role} is not an agent role")
    known = [r for r in brands if r in catalog.roles]
    for controller in known:
        for controlled in known:
            if (
                controller != controlled
                and catalog.controls(controller, controlled)
                and brands[controller] == brands[controlled]
            ):
                message = f"{controller} controls {controlled} but both are {brands[controller]}"
                if (controller, controlled) in EXERCISED:
                    problems.append(message)
                else:
                    warnings.append(message + " (not exercised in the first run)")
    for judge in MILESTONE_JUDGES:
        for builder in BUILDERS:
            if (
                judge in brands
                and builder in brands
                and brands[judge] == brands[builder]
            ):
                problems.append(
                    f"{judge} judges code built by {builder}, both {brands[judge]}"
                )
    if brands.get("test_designer") == brands.get("coder"):
        problems.append("the coder must not come from the test designer's producer")
    envs = [p["env"] for p in config["profiles"]]
    if len(envs) != len(set(envs)):
        problems.append("two profiles share an environment variable")
    if len(set(brands.values())) < 3:
        problems.append("the first run needs at least three producers")
    return {"problems": sorted(set(problems)), "warnings": sorted(set(warnings))}


# --------------------------------------------------------------------- #
# Bot Catalog setup through the DOR API
# --------------------------------------------------------------------- #
class Api:
    def __init__(self, base_url: str, token: str, organization_id: str) -> None:
        from services.llm_adapters import validate_http_url

        self._base = validate_http_url(base_url).rstrip("/")
        self._token = token
        self.organization_id = organization_id

    def call(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> tuple[int, Any]:
        sep = "&" if "?" in path else "?"
        url = f"{self._base}{path}{sep}organization_id={self.organization_id}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:  # nosec B310 - base URL validated as HTTP(S) in __init__.
                return response.status, json.loads(response.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")


def setup(
    config: Mapping[str, Any], api: Api, environ: Mapping[str, str] = os.environ
) -> list[str]:
    """Create connections, credentials, deployments and profiles; returns a log.

    Existing entries (409) are kept as they are; any other error stops."""
    from services.bot_provider_credentials import credential_reference

    log: list[str] = []
    gov = "/api/v1/bot-governance"

    def ok(status: int, what: str, body: Any) -> None:
        if status in (200, 201):
            log.append(f"created {what}")
        elif status == 409:
            log.append(f"exists {what}")
        else:
            raise FirstRunError(f"{what}: HTTP {status}: {body}")

    budget = config.get("budget") or {}
    for connection in config["connections"]:
        key = environ.get(connection["key_env"], "").strip()
        if not key:
            raise FirstRunError(f"set {connection['key_env']} before setup")
        status, body = api.call(
            "POST",
            f"{gov}/connections",
            {
                "command_id": str(uuid.uuid4()),
                "connection_id": connection["connection_id"],
                "brand": connection["brand"],
                "adapter_type": connection["adapter_type"],
                "endpoint": connection["endpoint"],
                "secret_reference": credential_reference(connection["connection_id"]),
                "region": connection.get("region"),
                "data_boundary": connection.get("data_boundary", "global"),
            },
        )
        ok(status, f"connection {connection['connection_id']}", body)
        status, body = api.call(
            "PUT",
            f"/api/v1/control-plane/organizations/{api.organization_id}/bot-provider-credentials/{connection['connection_id']}",
            {"api_key": key},
        )
        if status not in (200, 201):
            raise FirstRunError(
                f"credential {connection['connection_id']}: HTTP {status}"
            )
        log.append(f"stored credential {connection['connection_id']} (key not shown)")
    for deployment in config["deployments"]:
        status, body = api.call(
            "POST",
            f"{gov}/deployments",
            {
                "command_id": str(uuid.uuid4()),
                "deployment_id": deployment["deployment_id"],
                "connection_id": deployment["connection_id"],
                "connection_version": 1,
                "model_id": deployment["model_id"],
                "model_family": deployment["model_family"],
                "max_context_tokens": deployment["max_context_tokens"],
                "max_output_tokens": deployment["max_output_tokens"],
                "structured_output": True,
            },
        )
        ok(status, f"deployment {deployment['deployment_id']}", body)
    for profile in config["profiles"]:
        status, body = api.call(
            "POST",
            f"{gov}/profiles",
            {
                "command_id": str(uuid.uuid4()),
                "bot_profile_id": profile["bot_profile_id"],
                "display_name": f"{profile['role']} (first run)",
                "deployment_id": profile["deployment_id"],
                "deployment_revision": 1,
                "prompt_version": "registry",
                "capabilities": [profile["role"]],
                "budget_policy": {
                    "max_input_tokens": budget.get("max_input_tokens", 120000),
                    "max_output_tokens": budget.get("max_output_tokens", 16000),
                },
                "enabled": False,
            },
        )
        ok(status, f"profile {profile['bot_profile_id']}", body)
        status, body = api.call(
            "POST",
            f"{gov}/profiles/{profile['bot_profile_id']}/activate",
            {"command_id": str(uuid.uuid4())},
        )
        if status not in (200, 201, 409):
            raise FirstRunError(
                f"activate {profile['bot_profile_id']}: HTTP {status}: {body}"
            )
        log.append(f"active profile {profile['bot_profile_id']}")
    return log


def environment_lines(config: Mapping[str, Any]) -> list[str]:
    lines = [f"export {p['env']}={p['bot_profile_id']}" for p in config["profiles"]]
    lines += [
        f"export DOR_TEST_DESIGNER_AGENT={config['agents']['test_designer']['agent']}",
        f"export DOR_CODER_AGENT={config['agents']['coder']['agent']}",
    ]
    return lines


# --------------------------------------------------------------------- #
# Driving the milestone
# --------------------------------------------------------------------- #
def _status(path: str) -> dict[str, Any]:
    status = json.loads(Path(path).read_text(encoding="utf-8"))
    context = status.get("context") or status
    for key in ("work_plan", "contracts", "requirements"):
        if not context.get(key):
            raise FirstRunError(
                f"the pipeline status has no {key}; is the contracts gate approved?"
            )
    return context


def build_runner(repo: str, organization_id: str, config: Mapping[str, Any]):
    from api.dependencies import resolve_bot_model_for
    from execution.milestone import FileMilestoneStore, MilestoneRunner
    from execution.package_control import (
        AgentChoice,
        PackageLine,
        default_package_control,
    )
    from execution.worker_adapter import WorkerAdapter
    from services.agent_log_store import FileAgentLogStore
    from services.factory_workspace import FactoryWorkspaceManager

    problems = check_config(config)
    if problems:
        raise FirstRunError("; ".join(problems))
    workspaces = FactoryWorkspaceManager(repo)
    control = default_package_control(organization_id, workspaces)
    if control is None:
        raise FirstRunError(
            "the package controls are not configured; run `env` and export the profiles"
        )

    def profile(env: str):
        value = os.getenv(env, "").strip()
        if not value:
            raise FirstRunError(f"{env} is not set")
        return resolve_bot_model_for(organization_id, value)

    runner = MilestoneRunner(
        workspaces,
        PackageLine(
            WorkerAdapter(workspaces, FileAgentLogStore.from_environment()),
            control,
            workspaces,
        ),
        control,
        FileMilestoneStore.from_environment(),
        whole_controller=profile("DOR_CONTEXT_CONTROLLER_BOT_PROFILE"),
        governance={
            "system_architect": profile("DOR_SYSTEM_ARCHITECT_BOT_PROFILE"),
            "product_owner": profile("DOR_PRODUCT_OWNER_BOT_PROFILE"),
            "release_manager": profile("DOR_RELEASE_MANAGER_BOT_PROFILE"),
        },
    )
    agents = config["agents"]

    def coder(package: Mapping[str, Any]) -> AgentChoice:
        agent = agents[
            "test_designer"
            if package.get("task_type") == "contract_foundation"
            else "coder"
        ]
        key = os.getenv(agent["key_env"], "").strip()
        if not key:
            raise FirstRunError(f"set {agent['key_env']} for {agent['agent']}")
        return AgentChoice(agent["agent"], key)

    return runner, coder


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="First end-to-end run (DOR step 8a).")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("env")
    s = sub.add_parser("setup")
    s.add_argument("--api", required=True)
    s.add_argument("--organization", required=True)
    for name in ("start", "sprint", "finish"):
        p = sub.add_parser(name)
        p.add_argument("--repo", required=True)
        p.add_argument("--organization", required=True)
        p.add_argument(
            "--status",
            required=True,
            help="pipeline status JSON after the contracts gate",
        )
        p.add_argument("--actor", required=True)
        if name == "start":
            p.add_argument(
                "--review-mode", choices=("daily", "exceptions"), default="daily"
            )
        if name == "sprint":
            p.add_argument("--number", type=int, required=True)
    args = parser.parse_args(argv)
    config = load_config(Path(args.config))
    try:
        if args.command == "check":
            report = assignment_report(config)
            for problem in report["problems"]:
                print(f"problem: {problem}")
            for warning in report["warnings"]:
                print(f"warning: {warning}")
            if not report["problems"]:
                print("the role assignment allows the first run")
            return 1 if report["problems"] else 0
        if args.command == "env":
            print("\n".join(environment_lines(config)))
            return 0
        if args.command == "setup":
            token = os.getenv("DOR_API_TOKEN", "").strip()
            if not token:
                raise FirstRunError("set DOR_API_TOKEN (POST /auth/token) before setup")
            problems = check_config(config)
            if problems:
                raise FirstRunError("; ".join(problems))
            print("\n".join(setup(config, Api(args.api, token, args.organization))))
            return 0
        context = _status(args.status)
        runner, coder = build_runner(args.repo, args.organization, config)
        plan = context["work_plan"]
        contracts = context["contracts"]
        kravspec = context["requirements"]
        if args.command == "start":
            fingerprint = (context.get("requirements_ref") or {}).get(
                "fingerprint"
            ) or ""
            state = runner.start(
                plan,
                requirements_fingerprint=fingerprint,
                actor=args.actor,
                review_mode=args.review_mode,
            )
        elif args.command == "sprint":
            milestone = str(plan["milestone_id"])
            state = runner.start_sprint(milestone, args.number, actor=args.actor)
            if state["sprints"][-1]["status"] == "started":
                state = runner.run_sprint(
                    milestone,
                    args.number,
                    plan,
                    contracts,
                    kravspec,
                    coder=coder,
                    fresh_coder=None,
                    execution_id=str(context.get("workflow_id") or milestone),
                    organization_id=args.organization,
                    actor_id=args.actor,
                    architecture=(
                        (context.get("architecture") or {}).get("council") or {}
                    ).get("proposal"),
                )
        else:
            state = runner.finish(
                str(plan["milestone_id"]),
                contracts,
                kravspec,
                organization_id=args.organization,
                actor_id=args.actor,
                architecture=(
                    (context.get("architecture") or {}).get("council") or {}
                ).get("proposal"),
            )
    except FirstRunError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {k: state.get(k) for k in ("milestone_id", "status", "branch")}
            | {"last_sprint": (state.get("sprints") or [{}])[-1].get("status")},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
