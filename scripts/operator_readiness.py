"""Post-deploy operator readiness checks for the canonical Docker Compose runtime.

The command is intentionally read-only. It verifies build-context hygiene,
container health, API liveness/readiness, schema head, and Streamlit health.
It never prints configured secrets or mutates runtime state.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_RUNTIME_SERVICES = (
    "postgres",
    "minio",
    "api",
    "worker",
    "dashboard",
    "otel-collector",
)
_ONE_SHOT_SERVICES = ("migrate",)
_ENV_SENTINELS = (
    ".env",
    ".env.local",
    ".env.production",
    ".env.demo",
    ".env.demo.bak",
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _pass(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="PASS", detail=detail)


def _fail(name: str, detail: str) -> CheckResult:
    return CheckResult(name=name, status="FAIL", detail=detail)


def _dockerignore_patterns(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _is_ignored(name: str, patterns: list[str]) -> bool:
    """Evaluate the subset of Docker ignore semantics needed by secret sentinels."""
    ignored = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        pattern = pattern.lstrip("./")
        if not pattern:
            continue
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(f"/{name}", raw_pattern):
            ignored = not negated
    return ignored


def check_build_context(dockerignore: Path) -> CheckResult:
    """Fail when common local secret files can enter the Docker build context."""
    name = "build_context"
    try:
        patterns = _dockerignore_patterns(dockerignore)
    except OSError:
        return _fail(name, ".dockerignore is missing or unreadable")

    missing = [sentinel for sentinel in _ENV_SENTINELS if not _is_ignored(sentinel, patterns)]
    if missing:
        return _fail(
            name,
            "Docker build context does not exclude required env-secret patterns",
        )
    if not _is_ignored(".git", patterns):
        return _fail(name, "Docker build context does not exclude .git")
    return _pass(name, "Docker context excludes .git and common .env secret variants")


def parse_compose_ps(output: str) -> list[dict[str, Any]]:
    """Parse Docker Compose JSON output across array and JSON-lines variants."""
    text = output.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        records: list[dict[str, Any]] = []
        for line in text.splitlines():
            value = json.loads(line)
            if isinstance(value, dict):
                records.append(value)
        return records
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        return [payload]
    return []


def _exit_code(record: dict[str, Any]) -> int | None:
    value = record.get("ExitCode")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def evaluate_compose_records(records: list[dict[str, Any]]) -> list[CheckResult]:
    by_service: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        service = str(record.get("Service") or "").strip()
        if service:
            by_service.setdefault(service, []).append(record)

    results: list[CheckResult] = []
    for service in _RUNTIME_SERVICES:
        instances = by_service.get(service, [])
        if not instances:
            results.append(_fail(f"compose:{service}", "service is not present"))
            continue

        unhealthy: list[str] = []
        for record in instances:
            state = str(record.get("State") or "").strip().lower()
            health = str(record.get("Health") or "").strip().lower()
            if state != "running" or health != "healthy":
                unhealthy.append(f"state={state or 'unknown'},health={health or 'unknown'}")
        if unhealthy:
            results.append(
                _fail(
                    f"compose:{service}",
                    f"{len(unhealthy)} instance(s) are not running+healthy",
                )
            )
        else:
            results.append(
                _pass(
                    f"compose:{service}",
                    f"{len(instances)} instance(s) running and healthy",
                )
            )

    for service in _ONE_SHOT_SERVICES:
        instances = by_service.get(service, [])
        if not instances:
            results.append(_fail(f"compose:{service}", "one-shot service is not present"))
            continue
        completed = all(
            str(record.get("State") or "").strip().lower() in {"exited", "completed"}
            and _exit_code(record) == 0
            for record in instances
        )
        if completed:
            results.append(_pass(f"compose:{service}", "completed successfully"))
        else:
            results.append(_fail(f"compose:{service}", "did not complete successfully"))
    return results


def check_compose(
    compose_file: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[CheckResult]:
    name = "compose_ps"
    command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "ps",
        "--all",
        "--format",
        "json",
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return [_fail(name, "docker compose is unavailable")]
    if completed.returncode != 0:
        return [_fail(name, "docker compose ps failed")]
    try:
        records = parse_compose_ps(completed.stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        return [_fail(name, "docker compose ps returned invalid JSON")]
    if not records:
        return [_fail(name, "docker compose reported no services")]
    return [_pass(name, "docker compose state loaded"), *evaluate_compose_records(records)]


def _http_get(url: str, timeout: float) -> tuple[int, str]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "dor-operator-readiness/1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied HTTP(S) endpoint
        return int(response.status), response.read().decode("utf-8", errors="replace")


def _safe_http_get(
    url: str,
    timeout: float,
    getter: Callable[[str, float], tuple[int, str]],
) -> tuple[int | None, str | None]:
    try:
        return getter(url, timeout)
    except HTTPError as exc:
        return int(exc.code), None
    except (URLError, TimeoutError, OSError):
        return None, None


def check_api(
    api_url: str,
    state_file: Path,
    *,
    timeout: float,
    getter: Callable[[str, float], tuple[int, str]] = _http_get,
) -> list[CheckResult]:
    base = api_url.rstrip("/")
    results: list[CheckResult] = []

    status_code, body = _safe_http_get(f"{base}/health", timeout, getter)
    if status_code != 200 or body is None:
        results.append(_fail("api_liveness", f"HTTP status {status_code or 'unreachable'}"))
    else:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and payload.get("status") == "ok":
            results.append(_pass("api_liveness", "API /health reports ok"))
        else:
            results.append(_fail("api_liveness", "API /health payload is not canonical"))

    status_code, body = _safe_http_get(f"{base}/health/ready", timeout, getter)
    if status_code != 200 or body is None:
        results.append(_fail("api_readiness", f"HTTP status {status_code or 'unreachable'}"))
        return results

    try:
        payload = json.loads(body)
        expected = json.loads(state_file.read_text(encoding="utf-8"))["canonical_alembic_head"]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        results.append(_fail("api_readiness", "readiness contract could not be evaluated"))
        return results

    if not isinstance(payload, dict):
        results.append(_fail("api_readiness", "API readiness payload is not an object"))
    elif (
        payload.get("status") == "ready"
        and payload.get("database") == "ok"
        and payload.get("migration_head") == expected
    ):
        results.append(
            _pass(
                "api_readiness",
                f"database ready at canonical Alembic head {expected}",
            )
        )
    else:
        results.append(_fail("api_readiness", "API readiness does not match canonical schema state"))
    return results


def check_dashboard(
    dashboard_url: str,
    *,
    timeout: float,
    getter: Callable[[str, float], tuple[int, str]] = _http_get,
) -> CheckResult:
    url = f"{dashboard_url.rstrip('/')}/_stcore/health"
    status_code, body = _safe_http_get(url, timeout, getter)
    if status_code != 200 or body is None:
        return _fail("dashboard_health", f"HTTP status {status_code or 'unreachable'}")
    if body.strip().lower() != "ok":
        return _fail("dashboard_health", "Streamlit health payload is not ok")
    return _pass("dashboard_health", "Streamlit health reports ok")


def build_report(results: list[CheckResult]) -> dict[str, Any]:
    failures = [result.name for result in results if not result.passed]
    return {
        "classification": "READY" if not failures else "NOT_READY",
        "checks": [asdict(result) for result in results],
        "errors": failures,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a running DOR Compose deployment")
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path(os.environ.get("DOR_COMPOSE_FILE", "compose.yml")),
    )
    parser.add_argument("--dockerignore", type=Path, default=Path(".dockerignore"))
    parser.add_argument("--state-file", type=Path, default=Path("docs/CURRENT_STATE.json"))
    parser.add_argument(
        "--api-url",
        default=os.environ.get(
            "DOR_READINESS_API_URL",
            f"http://127.0.0.1:{os.environ.get('DOR_API_PORT', '8000')}",
        ),
    )
    parser.add_argument(
        "--dashboard-url",
        default=os.environ.get(
            "DOR_READINESS_DASHBOARD_URL",
            f"http://127.0.0.1:{os.environ.get('DOR_DASHBOARD_PORT', '8501')}",
        ),
    )
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    results = [check_build_context(args.dockerignore)]
    results.extend(check_compose(args.compose_file))
    results.extend(
        check_api(
            args.api_url,
            args.state_file,
            timeout=args.timeout,
        )
    )
    results.append(
        check_dashboard(
            args.dashboard_url,
            timeout=args.timeout,
        )
    )
    report = build_report(results)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["classification"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
