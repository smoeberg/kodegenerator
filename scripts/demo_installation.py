"""Deterministic seed, preflight, reset, and certification for the DOR demo stack."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet

from scripts.operator_readiness import (
    check_api,
    check_build_context,
    check_dashboard,
    evaluate_compose_records,
    parse_compose_ps,
)


DEMO_REPOSITORY = "repository:demo/golden"
DEMO_ORGANIZATION = "dor-demo-org"
DEMO_CHECKOUT_NAME = "golden"
DEMO_ALLOWED_TOOLS = "python.ruff,python.pytest,python.compileall"
COMPOSE_FILES = (Path("compose.yml"), Path("compose.demo.yml"))
_REQUIRED_ENV = (
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "MINIO_ROOT_USER",
    "MINIO_ROOT_PASSWORD",
    "DOR_ADMIN_USERNAME",
    "DOR_ADMIN_PASSWORD",
    "DOR_ORGANIZATION_ID",
    "DOR_WORKER_SERVICE_ID",
    "DOR_WORKER_CREDENTIAL",
    "DOR_WORKER_CAPABILITIES",
    "DOR_JWT_SIGNING_KEYS",
    "DOR_JWT_ACTIVE_KEY_ID",
    "DOR_AUTHORITY_SIGNING_KEY",
    "DOR_ENCRYPTION_KEY",
    "OPENAI_API_KEY",
    "DOR_IMPLEMENTATION_MODEL",
    "DOR_IMPLEMENTATION_ALLOWED_RESOURCES",
    "DOR_PATCH_ALLOWED_TOOLS",
    "DOR_DEMO_AUDIT_CHECKOUTS_HOST_ROOT",
    "DOR_DEMO_AUDIT_CATALOG_HOST_FILE",
    "DOR_DEMO_PATCH_WORKSPACE_HOST",
)
_FORBIDDEN_PLACEHOLDER_FRAGMENTS = (
    "generated-",
    "replace-with-",
    "example.invalid",
)


@dataclass(frozen=True)
class DemoCheck:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _pass(name: str, detail: str) -> DemoCheck:
    return DemoCheck(name, "PASS", detail)


def _fail(name: str, detail: str) -> DemoCheck:
    return DemoCheck(name, "FAIL", detail)


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        command,
        cwd=str(cwd) if cwd is not None else None,
        env=dict(env) if env is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )


def _git_environment() -> dict[str, str]:
    return {
        "PATH": os.defpath,
        "HOME": os.environ.get("HOME", "/tmp"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "DOR Demo",
        "GIT_AUTHOR_EMAIL": "demo@example.invalid",
        "GIT_COMMITTER_NAME": "DOR Demo",
        "GIT_COMMITTER_EMAIL": "demo@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
        "LC_ALL": "C.UTF-8",
        "LANG": "C.UTF-8",
    }


def _require_success(
    completed: subprocess.CompletedProcess[str],
    action: str,
) -> None:
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{action} failed: {detail or 'unknown error'}")


def _copy_fixture(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise RuntimeError(f"demo fixture is missing: {source}")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _initialize_git_checkout(path: Path) -> str:
    environment = _git_environment()
    for command, action in (
        (["git", "init", "--initial-branch=main"], "git init"),
        (["git", "add", "--all"], "git add"),
        (["git", "commit", "-m", "DOR golden demo baseline"], "git commit"),
    ):
        _require_success(_run(command, cwd=path, env=environment), action)
    completed = _run(["git", "rev-parse", "HEAD"], cwd=path, env=environment)
    _require_success(completed, "git rev-parse")
    return completed.stdout.strip()


def seed_workspaces(*, root: Path, fixture: Path) -> dict[str, str]:
    """Create separate audit/read-only and patch/read-write checkouts at one baseline."""
    root = root.resolve()
    audit_root = root / "audit-checkouts"
    audit_checkout = audit_root / DEMO_CHECKOUT_NAME
    patch_workspace = root / "patch-workspace"
    catalog_file = root / "project-audit-checkouts.json"

    root.mkdir(parents=True, exist_ok=True)
    audit_root.mkdir(parents=True, exist_ok=True)
    _copy_fixture(fixture, audit_checkout)
    baseline_sha = _initialize_git_checkout(audit_checkout)
    if patch_workspace.exists():
        shutil.rmtree(patch_workspace)
    completed = _run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            str(audit_checkout),
            str(patch_workspace),
        ],
        env=_git_environment(),
    )
    _require_success(completed, "git clone demo patch workspace")

    payload = {
        "version": 1,
        "repositories": [
            {
                "organization_id": DEMO_ORGANIZATION,
                "repository": DEMO_REPOSITORY,
                "checkout": DEMO_CHECKOUT_NAME,
            }
        ],
    }
    catalog_file.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "audit_root": str(audit_root),
        "audit_checkout": str(audit_checkout),
        "patch_workspace": str(patch_workspace),
        "catalog_file": str(catalog_file),
        "baseline_sha": baseline_sha,
    }


def _generated_demo_environment(
    *,
    paths: Mapping[str, str],
    environ: Mapping[str, str],
) -> dict[str, str]:
    provider_key = environ.get("OPENAI_API_KEY", "").strip()
    model = environ.get("DOR_IMPLEMENTATION_MODEL", "").strip()
    if not provider_key:
        raise RuntimeError("OPENAI_API_KEY must be exported before demo-seed")
    if not model:
        raise RuntimeError("DOR_IMPLEMENTATION_MODEL must be exported before demo-seed")

    jwt_key = secrets.token_urlsafe(32)
    jwt_key_id = "dor-demo-v1"
    return {
        "POSTGRES_DB": "dor_demo",
        "POSTGRES_USER": "dor_demo",
        "POSTGRES_PASSWORD": secrets.token_urlsafe(32),
        "MINIO_ROOT_USER": "dor-demo",
        "MINIO_ROOT_PASSWORD": secrets.token_urlsafe(32),
        "ARTIFACT_BUCKET": "dor-demo-artifacts",
        "AWS_DEFAULT_REGION": "eu-central-1",
        "DOR_ADMIN_USERNAME": "admin",
        "DOR_ADMIN_ORGANIZATION_ID": DEMO_ORGANIZATION,
        "DOR_ADMIN_PASSWORD": secrets.token_urlsafe(32),
        "DOR_ORGANIZATION_ID": DEMO_ORGANIZATION,
        "DOR_WORKER_SERVICE_ID": "factory-worker",
        "DOR_WORKER_CREDENTIAL": secrets.token_urlsafe(32),
        "DOR_WORKER_CAPABILITIES": (
            "pipeline.architecture,pipeline.code,pipeline.contracts,"
            "pipeline.deploy,pipeline.release,pipeline.tests"
        ),
        "DOR_WORKER_REPLICAS": "2",
        "DOR_JWT_SIGNING_KEYS": json.dumps(
            {jwt_key_id: jwt_key},
            separators=(",", ":"),
        ),
        "DOR_JWT_ACTIVE_KEY_ID": jwt_key_id,
        "DOR_AUTHORITY_SIGNING_KEY": base64.urlsafe_b64encode(
            secrets.token_bytes(32)
        ).decode("ascii"),
        "DOR_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
        "DOR_API_PORT": environ.get("DOR_API_PORT", "8000").strip() or "8000",
        "DOR_DASHBOARD_PORT": (
            environ.get("DOR_DASHBOARD_PORT", "8501").strip() or "8501"
        ),
        "OPENAI_API_KEY": provider_key,
        "DOR_IMPLEMENTATION_MODEL": model,
        "DOR_IMPLEMENTATION_ALLOWED_RESOURCES": DEMO_REPOSITORY,
        "DOR_PATCH_ALLOWED_TOOLS": DEMO_ALLOWED_TOOLS,
        "DOR_DEMO_AUDIT_CHECKOUTS_HOST_ROOT": paths["audit_root"],
        "DOR_DEMO_AUDIT_CATALOG_HOST_FILE": paths["catalog_file"],
        "DOR_DEMO_PATCH_WORKSPACE_HOST": paths["patch_workspace"],
    }


def write_env_file(path: Path, values: Mapping[str, str]) -> None:
    """Write the generated secret-bearing demo env file without echoing values."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated by scripts/demo_installation.py. Contains secrets; never commit.",
        *[f"{key}={value}" for key, value in values.items()],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError(
            f"demo env file is missing or unreadable: {path}"
        ) from exc
    for index, raw in enumerate(lines, start=1):
        text = raw.strip()
        if not text or text.startswith("#"):
            continue
        if "=" not in text:
            raise RuntimeError(f"invalid env line {index}")
        key, value = text.split("=", 1)
        key = key.strip()
        if not key or key in values:
            raise RuntimeError(f"invalid or duplicate env key on line {index}")
        values[key] = value
    return values


def validate_env(values: Mapping[str, str]) -> list[DemoCheck]:
    results: list[DemoCheck] = []
    missing = [name for name in _REQUIRED_ENV if not values.get(name, "").strip()]
    if missing:
        results.append(
            _fail(
                "environment_required",
                "missing required demo variables: " + ", ".join(missing),
            )
        )
    else:
        results.append(
            _pass(
                "environment_required",
                "all required demo variables are present",
            )
        )

    placeholder_names = [
        name
        for name, value in values.items()
        if any(
            fragment in value.lower()
            for fragment in _FORBIDDEN_PLACEHOLDER_FRAGMENTS
        )
    ]
    if placeholder_names:
        results.append(
            _fail(
                "environment_placeholders",
                "placeholder values remain in: "
                + ", ".join(sorted(placeholder_names)),
            )
        )
    else:
        results.append(
            _pass(
                "environment_placeholders",
                "no documentation placeholders are configured",
            )
        )

    if values.get("DOR_IMPLEMENTATION_ALLOWED_RESOURCES") == DEMO_REPOSITORY:
        results.append(
            _pass(
                "implementation_resource",
                f"Implementation Agent is bound to {DEMO_REPOSITORY}",
            )
        )
    else:
        results.append(
            _fail(
                "implementation_resource",
                "Implementation Agent resource is not the golden demo repository",
            )
        )

    if values.get("DOR_PATCH_ALLOWED_TOOLS") == DEMO_ALLOWED_TOOLS:
        results.append(
            _pass(
                "patch_tools",
                "governed patch tools match the canonical Python toolchain",
            )
        )
    else:
        results.append(
            _fail(
                "patch_tools",
                "governed patch tool allowlist does not match the demo contract",
            )
        )
    return results


def check_seeded_workspaces(values: Mapping[str, str]) -> list[DemoCheck]:
    results: list[DemoCheck] = []
    audit_root = Path(values.get("DOR_DEMO_AUDIT_CHECKOUTS_HOST_ROOT", ""))
    catalog_file = Path(values.get("DOR_DEMO_AUDIT_CATALOG_HOST_FILE", ""))
    patch_root = Path(values.get("DOR_DEMO_PATCH_WORKSPACE_HOST", ""))

    if not audit_root.is_absolute() or not audit_root.is_dir():
        results.append(
            _fail(
                "audit_checkout_root",
                "audit checkout root is not an existing absolute directory",
            )
        )
    else:
        results.append(_pass("audit_checkout_root", "audit checkout root exists"))

    if not patch_root.is_absolute() or not patch_root.is_dir():
        results.append(
            _fail(
                "patch_workspace",
                "patch workspace is not an existing absolute directory",
            )
        )
    else:
        results.append(_pass("patch_workspace", "patch workspace exists"))

    try:
        payload = json.loads(catalog_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
    expected = {
        "version": 1,
        "repositories": [
            {
                "organization_id": DEMO_ORGANIZATION,
                "repository": DEMO_REPOSITORY,
                "checkout": DEMO_CHECKOUT_NAME,
            }
        ],
    }
    if payload == expected:
        results.append(
            _pass(
                "audit_catalog",
                "catalog binds the golden repository to the demo organization",
            )
        )
    else:
        results.append(
            _fail(
                "audit_catalog",
                "audit checkout catalog does not match the demo contract",
            )
        )

    audit_checkout = audit_root / DEMO_CHECKOUT_NAME
    for name, root in (("audit_git", audit_checkout), ("patch_git", patch_root)):
        completed = _run(
            ["git", "status", "--porcelain"],
            cwd=root,
            env=_git_environment(),
        )
        if completed.returncode == 0 and not completed.stdout.strip():
            results.append(_pass(name, "repository is a clean Git checkout"))
        else:
            results.append(_fail(name, "repository is missing, invalid, or dirty"))

    audit_head = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=audit_checkout,
        env=_git_environment(),
    )
    patch_head = _run(
        ["git", "rev-parse", "HEAD"],
        cwd=patch_root,
        env=_git_environment(),
    )
    if (
        audit_head.returncode == 0
        and patch_head.returncode == 0
        and audit_head.stdout.strip()
        and audit_head.stdout.strip() == patch_head.stdout.strip()
    ):
        results.append(
            _pass(
                "baseline_parity",
                "audit and patch workspaces share the exact Git baseline",
            )
        )
    else:
        results.append(
            _fail(
                "baseline_parity",
                "audit and patch workspace Git baselines differ",
            )
        )
    return results


def compose_command(env_file: Path, *arguments: str) -> list[str]:
    command = ["docker", "compose", "--env-file", str(env_file)]
    for compose_file in COMPOSE_FILES:
        command.extend(["-f", str(compose_file)])
    command.extend(arguments)
    return command


def check_compose_config(
    env_file: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[DemoCheck]:
    completed = _run(
        compose_command(env_file, "config", "--format", "json"),
        runner=runner,
    )
    if completed.returncode != 0:
        return [_fail("compose_config", "docker compose config failed")]
    try:
        payload = json.loads(completed.stdout)
        services = payload["services"]
        api_environment = services["api"]["environment"]
        dashboard_environment = services["dashboard"]["environment"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return [
            _fail(
                "compose_config",
                "docker compose config did not return the expected JSON contract",
            )
        ]

    results = [
        _pass(
            "compose_config",
            "base + demo Compose files render successfully",
        )
    ]
    if dashboard_environment.get("DOR_API_URL") == "http://api:8000":
        results.append(
            _pass(
                "dashboard_api_wiring",
                "dashboard uses the canonical DOR_API_URL",
            )
        )
    else:
        results.append(
            _fail(
                "dashboard_api_wiring",
                "dashboard is not wired to the canonical DOR_API_URL",
            )
        )

    if api_environment.get("DOR_PATCH_WORKSPACE_ROOT") == "/demo/patch-workspace":
        results.append(
            _pass(
                "patch_runtime_wiring",
                "API patch runtime uses the dedicated writable workspace",
            )
        )
    else:
        results.append(
            _fail(
                "patch_runtime_wiring",
                "API patch runtime workspace is not configured",
            )
        )

    if api_environment.get("DOR_IMPLEMENTATION_ALLOWED_RESOURCES") == DEMO_REPOSITORY:
        results.append(
            _pass(
                "implementation_runtime_wiring",
                "API Implementation Agent is scoped to the golden repository",
            )
        )
    else:
        results.append(
            _fail(
                "implementation_runtime_wiring",
                "API Implementation Agent resource scope drifted",
            )
        )
    return results


def build_report(
    results: list[DemoCheck],
    *,
    certified: bool,
) -> dict[str, Any]:
    failures = [item.name for item in results if not item.passed]
    if failures:
        classification = "NOT_CERTIFIED" if certified else "NOT_READY"
    else:
        classification = "CERTIFIED" if certified else "READY"
    return {
        "classification": classification,
        "checks": [asdict(item) for item in results],
        "errors": failures,
    }


def preflight(
    *,
    env_file: Path,
    dockerignore: Path = Path(".dockerignore"),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    try:
        values = load_env_file(env_file)
    except RuntimeError as exc:
        return build_report(
            [_fail("environment_file", str(exc))],
            certified=False,
        )
    results = validate_env(values)
    results.extend(check_seeded_workspaces(values))
    build_context = check_build_context(dockerignore)
    results.append(
        DemoCheck(
            build_context.name,
            build_context.status,
            build_context.detail,
        )
    )
    results.extend(check_compose_config(env_file, runner=runner))
    return build_report(results, certified=False)


def _compose_state(
    env_file: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[DemoCheck]:
    completed = _run(
        compose_command(env_file, "ps", "--all", "--format", "json"),
        runner=runner,
    )
    if completed.returncode != 0:
        return [_fail("compose_ps", "docker compose ps failed")]
    try:
        records = parse_compose_ps(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return [_fail("compose_ps", "docker compose ps returned invalid JSON")]
    if not records:
        return [_fail("compose_ps", "docker compose reported no services")]

    results = [_pass("compose_ps", "docker compose runtime state loaded")]
    for item in evaluate_compose_records(records):
        results.append(DemoCheck(item.name, item.status, item.detail))
    return results


def _exec_probe(
    env_file: Path,
    service: str,
    python_code: str,
    name: str,
    detail: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> DemoCheck:
    completed = _run(
        compose_command(
            env_file,
            "exec",
            "-T",
            service,
            "python",
            "-c",
            python_code,
        ),
        runner=runner,
    )
    if completed.returncode == 0 and completed.stdout.strip().endswith("READY"):
        return _pass(name, detail)
    return _fail(name, f"{service} runtime probe failed")


def _login_probe(
    api_url: str,
    *,
    username: str,
    password: str,
    timeout: float = 5.0,
) -> DemoCheck:
    body = urlencode({"username": username, "password": password}).encode("utf-8")
    request = Request(
        f"{api_url.rstrip('/')}/auth/token",
        data=body,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError):
        return _fail(
            "authenticated_bootstrap",
            "admin login/bootstrap probe failed",
        )
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        return _fail(
            "authenticated_bootstrap",
            "admin login did not return an access token",
        )

    protected = Request(
        f"{api_url.rstrip('/')}/protected",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(protected, timeout=timeout) as response:  # noqa: S310
            if int(response.status) != 200:
                return _fail(
                    "authenticated_bootstrap",
                    "authenticated protected probe failed",
                )
    except (HTTPError, URLError, TimeoutError, OSError):
        return _fail(
            "authenticated_bootstrap",
            "authenticated protected probe failed",
        )
    return _pass(
        "authenticated_bootstrap",
        "admin principal and organization bootstrap are usable",
    )


def certify(
    *,
    env_file: Path,
    state_file: Path = Path("docs/CURRENT_STATE.json"),
    dockerignore: Path = Path(".dockerignore"),
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Certify the running stack without invoking the external model provider."""
    static_report = preflight(
        env_file=env_file,
        dockerignore=dockerignore,
        runner=runner,
    )
    static_results = [
        DemoCheck(item["name"], item["status"], item["detail"])
        for item in static_report["checks"]
    ]
    if static_report["classification"] != "READY":
        return build_report(static_results, certified=True)

    values = load_env_file(env_file)
    api_url = f"http://127.0.0.1:{values.get('DOR_API_PORT', '8000')}"
    dashboard_url = (
        f"http://127.0.0.1:{values.get('DOR_DASHBOARD_PORT', '8501')}"
    )
    results = static_results
    results.extend(_compose_state(env_file, runner=runner))
    for item in check_api(api_url, state_file, timeout=5.0):
        results.append(DemoCheck(item.name, item.status, item.detail))
    dashboard = check_dashboard(dashboard_url, timeout=5.0)
    results.append(
        DemoCheck(
            dashboard.name,
            dashboard.status,
            dashboard.detail,
        )
    )
    results.append(
        _login_probe(
            api_url,
            username=values["DOR_ADMIN_USERNAME"],
            password=values["DOR_ADMIN_PASSWORD"],
        )
    )
    results.append(
        _exec_probe(
            env_file,
            "api",
            (
                "from api.dependencies import get_implementation_agent_runtime,"
                "get_governed_patch_runtime; "
                "get_implementation_agent_runtime(); get_governed_patch_runtime(); "
                "print('READY')"
            ),
            "implementation_agent_runtime",
            "Implementation Agent and governed patch runtime construct successfully",
            runner=runner,
        )
    )
    results.append(
        _exec_probe(
            env_file,
            "dashboard",
            (
                "from dashboard.repository_checkout_catalog import "
                "discover_repository_checkout; "
                f"b=discover_repository_checkout(organization_id='{DEMO_ORGANIZATION}', "
                f"repository='{DEMO_REPOSITORY}'); "
                f"b.root_for(organization_id='{DEMO_ORGANIZATION}', "
                f"repository='{DEMO_REPOSITORY}'); print('READY')"
            ),
            "project_audit_runtime",
            "dashboard resolves the governed read-only golden checkout",
            runner=runner,
        )
    )
    return build_report(results, certified=True)


def seed(
    *,
    root: Path,
    fixture: Path,
    env_file: Path,
    environ: Mapping[str, str] = os.environ,
) -> dict[str, Any]:
    """Seed deterministic workspaces and generate all non-provider demo secrets."""
    paths = seed_workspaces(root=root, fixture=fixture)
    values = _generated_demo_environment(paths=paths, environ=environ)
    write_env_file(env_file, values)
    return {
        "classification": "SEEDED",
        "repository": DEMO_REPOSITORY,
        "organization_id": DEMO_ORGANIZATION,
        "baseline_sha": paths["baseline_sha"],
        "env_file": str(env_file),
    }


def reset(
    *,
    root: Path,
    fixture: Path,
    env_file: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Remove runtime volumes and restore both demo checkouts to the golden baseline."""
    if env_file.is_file():
        completed = _run(
            compose_command(env_file, "down", "-v", "--remove-orphans"),
            runner=runner,
        )
        if completed.returncode != 0:
            raise RuntimeError("docker compose down failed during demo reset")

    paths = seed_workspaces(root=root, fixture=fixture)
    if env_file.is_file():
        values = load_env_file(env_file)
        values.update(
            {
                "DOR_DEMO_AUDIT_CHECKOUTS_HOST_ROOT": paths["audit_root"],
                "DOR_DEMO_AUDIT_CATALOG_HOST_FILE": paths["catalog_file"],
                "DOR_DEMO_PATCH_WORKSPACE_HOST": paths["patch_workspace"],
            }
        )
        write_env_file(env_file, values)
    return {
        "classification": "RESET",
        "repository": DEMO_REPOSITORY,
        "organization_id": DEMO_ORGANIZATION,
        "baseline_sha": paths["baseline_sha"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage the certified DOR demo installation"
    )
    parser.add_argument(
        "command",
        choices=("seed", "preflight", "certify", "reset"),
    )
    parser.add_argument("--root", type=Path, default=Path(".dor-demo"))
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("demo/golden_repository"),
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env.demo"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "seed":
            report = seed(
                root=args.root,
                fixture=args.fixture,
                env_file=args.env_file,
            )
        elif args.command == "preflight":
            report = preflight(env_file=args.env_file)
        elif args.command == "certify":
            report = certify(env_file=args.env_file)
        else:
            report = reset(
                root=args.root,
                fixture=args.fixture,
                env_file=args.env_file,
            )
    except RuntimeError as exc:
        report = {
            "classification": "ERROR",
            "checks": [],
            "errors": [str(exc)],
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        0
        if report["classification"]
        in {"SEEDED", "READY", "CERTIFIED", "RESET"}
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
