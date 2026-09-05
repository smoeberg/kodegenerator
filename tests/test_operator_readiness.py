from __future__ import annotations

import json
from pathlib import Path

from scripts.operator_readiness import (
    CheckResult,
    build_report,
    check_api,
    check_build_context,
    check_dashboard,
    evaluate_compose_records,
    parse_compose_ps,
)


def _healthy_compose_records() -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for service in (
        "postgres",
        "minio",
        "api",
        "dashboard",
        "otel-collector",
    ):
        records.append(
            {
                "Service": service,
                "State": "running",
                "Health": "healthy",
                "ExitCode": 0,
            }
        )
    records.extend(
        [
            {
                "Service": "worker",
                "State": "running",
                "Health": "healthy",
                "ExitCode": 0,
            },
            {
                "Service": "worker",
                "State": "running",
                "Health": "healthy",
                "ExitCode": 0,
            },
            {
                "Service": "migrate",
                "State": "exited",
                "Health": "",
                "ExitCode": 0,
            },
        ]
    )
    return records


def test_build_context_requires_git_and_env_secret_exclusions(tmp_path: Path) -> None:
    dockerignore = tmp_path / ".dockerignore"
    dockerignore.write_text(".git\n.env\n.env.*\n", encoding="utf-8")

    result = check_build_context(dockerignore)

    assert result.status == "PASS"

    dockerignore.write_text(".git\n.env\n", encoding="utf-8")
    result = check_build_context(dockerignore)
    assert result.status == "FAIL"
    assert "env-secret" in result.detail


def test_dockerignore_negation_fails_closed_for_secret_variant(tmp_path: Path) -> None:
    dockerignore = tmp_path / ".dockerignore"
    dockerignore.write_text(
        ".git\n.env\n.env.*\n!.env.demo\n",
        encoding="utf-8",
    )

    result = check_build_context(dockerignore)

    assert result.status == "FAIL"


def test_parse_compose_ps_supports_array_and_json_lines() -> None:
    records = _healthy_compose_records()

    assert parse_compose_ps(json.dumps(records)) == records
    json_lines = "\n".join(json.dumps(record) for record in records)
    assert parse_compose_ps(json_lines) == records


def test_compose_evaluation_requires_all_runtime_services_healthy() -> None:
    results = evaluate_compose_records(_healthy_compose_records())

    assert all(result.status == "PASS" for result in results)
    assert next(result for result in results if result.name == "compose:worker").detail.startswith(
        "2 instance(s)"
    )

    broken = _healthy_compose_records()
    broken[2] = {
        "Service": "api",
        "State": "running",
        "Health": "unhealthy",
        "ExitCode": 0,
    }
    results = evaluate_compose_records(broken)
    assert next(result for result in results if result.name == "compose:api").status == "FAIL"


def test_compose_evaluation_requires_successful_migration() -> None:
    broken = _healthy_compose_records()
    broken[-1] = {
        "Service": "migrate",
        "State": "exited",
        "Health": "",
        "ExitCode": 1,
    }

    results = evaluate_compose_records(broken)

    assert next(result for result in results if result.name == "compose:migrate").status == "FAIL"


def test_api_readiness_requires_canonical_alembic_head(tmp_path: Path) -> None:
    state_file = tmp_path / "CURRENT_STATE.json"
    state_file.write_text(
        json.dumps({"canonical_alembic_head": "025_swarm_control_state"}),
        encoding="utf-8",
    )

    def getter(url: str, _timeout: float) -> tuple[int, str]:
        if url.endswith("/health/ready"):
            return (
                200,
                json.dumps(
                    {
                        "status": "ready",
                        "database": "ok",
                        "migration_head": "025_swarm_control_state",
                    }
                ),
            )
        return 200, json.dumps({"status": "ok"})

    results = check_api(
        "http://api.example",
        state_file,
        timeout=1,
        getter=getter,
    )

    assert [result.status for result in results] == ["PASS", "PASS"]

    def stale_getter(url: str, _timeout: float) -> tuple[int, str]:
        if url.endswith("/health/ready"):
            return 200, json.dumps(
                {
                    "status": "ready",
                    "database": "ok",
                    "migration_head": "024_old_head",
                }
            )
        return 200, json.dumps({"status": "ok"})

    results = check_api(
        "http://api.example",
        state_file,
        timeout=1,
        getter=stale_getter,
    )
    assert results[1].status == "FAIL"


def test_api_and_dashboard_fail_closed_on_unreachable_endpoints(tmp_path: Path) -> None:
    state_file = tmp_path / "CURRENT_STATE.json"
    state_file.write_text(
        json.dumps({"canonical_alembic_head": "025_swarm_control_state"}),
        encoding="utf-8",
    )

    def unreachable(_url: str, _timeout: float) -> tuple[int, str]:
        raise OSError("offline")

    api_results = check_api(
        "http://api.example",
        state_file,
        timeout=1,
        getter=unreachable,
    )
    dashboard = check_dashboard(
        "http://dashboard.example",
        timeout=1,
        getter=unreachable,
    )

    assert [result.status for result in api_results] == ["FAIL", "FAIL"]
    assert dashboard.status == "FAIL"


def test_report_is_ready_only_when_every_check_passes() -> None:
    ready = build_report(
        [
            CheckResult("one", "PASS", "ok"),
            CheckResult("two", "PASS", "ok"),
        ]
    )
    assert ready == {
        "classification": "READY",
        "checks": [
            {"name": "one", "status": "PASS", "detail": "ok"},
            {"name": "two", "status": "PASS", "detail": "ok"},
        ],
        "errors": [],
    }

    blocked = build_report(
        [
            CheckResult("one", "PASS", "ok"),
            CheckResult("two", "FAIL", "bad"),
        ]
    )
    assert blocked["classification"] == "NOT_READY"
    assert blocked["errors"] == ["two"]
