from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.demo_installation import (
    DEMO_ALLOWED_TOOLS,
    DEMO_ORGANIZATION,
    DEMO_REPOSITORY,
    _generated_demo_environment,
    check_compose_config,
    seed_workspaces,
    validate_env,
)
from services.runtime_configuration import _ROLE_REQUIRED


def test_seed_workspaces_creates_distinct_clean_checkouts_at_same_baseline(
    tmp_path: Path,
) -> None:
    fixture = Path("demo/golden_repository").resolve()
    paths = seed_workspaces(root=tmp_path / "runtime", fixture=fixture)

    audit = Path(paths["audit_checkout"])
    patch = Path(paths["patch_workspace"])
    assert audit != patch
    assert (audit / ".git").is_dir()
    assert (patch / ".git").is_dir()

    def git(root: Path, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        return completed.stdout.strip()

    assert git(audit, "rev-parse", "HEAD") == git(patch, "rev-parse", "HEAD")
    assert git(audit, "status", "--porcelain") == ""
    assert git(patch, "status", "--porcelain") == ""

    catalog = json.loads(Path(paths["catalog_file"]).read_text(encoding="utf-8"))
    assert catalog == {
        "version": 1,
        "repositories": [
            {
                "organization_id": DEMO_ORGANIZATION,
                "repository": DEMO_REPOSITORY,
                "checkout": "golden",
            }
        ],
    }


def test_generated_environment_is_provider_bound_and_has_no_placeholders(
    tmp_path: Path,
) -> None:
    audit = (tmp_path / "audit").resolve()
    patch = (tmp_path / "patch").resolve()
    audit.mkdir()
    patch.mkdir()
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{}", encoding="utf-8")

    values = _generated_demo_environment(
        paths={
            "audit_root": str(audit),
            "patch_workspace": str(patch),
            "catalog_file": str(catalog.resolve()),
        },
        environ={
            "OPENAI_API_KEY": "test-provider-key",
            "DOR_IMPLEMENTATION_MODEL": "test-model",
        },
    )

    assert values["DOR_IMPLEMENTATION_ALLOWED_RESOURCES"] == DEMO_REPOSITORY
    assert values["DOR_PATCH_ALLOWED_TOOLS"] == DEMO_ALLOWED_TOOLS
    assert values["DOR_ORGANIZATION_ID"] == DEMO_ORGANIZATION
    assert all(item.passed for item in validate_env(values))


def test_generated_environment_requires_explicit_provider_configuration(
    tmp_path: Path,
) -> None:
    paths = {
        "audit_root": str(tmp_path.resolve()),
        "patch_workspace": str(tmp_path.resolve()),
        "catalog_file": str((tmp_path / "catalog.json").resolve()),
    }
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        _generated_demo_environment(paths=paths, environ={})
    with pytest.raises(RuntimeError, match="DOR_IMPLEMENTATION_MODEL"):
        _generated_demo_environment(
            paths=paths,
            environ={"OPENAI_API_KEY": "test-provider-key"},
        )


def test_compose_preflight_locks_api_dashboard_and_patch_wiring(tmp_path: Path) -> None:
    payload = {
        "services": {
            "api": {
                "environment": {
                    "DOR_PATCH_WORKSPACE_ROOT": "/demo/patch-workspace",
                    "DOR_IMPLEMENTATION_ALLOWED_RESOURCES": DEMO_REPOSITORY,
                }
            },
            "dashboard": {
                "environment": {
                    "DOR_API_URL": "http://api:8000",
                }
            },
        }
    }

    def runner(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    results = check_compose_config(tmp_path / ".env.demo", runner=runner)
    assert {item.name for item in results} == {
        "compose_config",
        "dashboard_api_wiring",
        "patch_runtime_wiring",
        "implementation_runtime_wiring",
    }
    assert all(item.passed for item in results)


def test_dashboard_runtime_contract_uses_canonical_api_url() -> None:
    assert "DOR_API_URL" in _ROLE_REQUIRED["dashboard"]
    assert "DOR_API_BASE" not in _ROLE_REQUIRED["dashboard"]


def test_repository_declares_certified_demo_as_canonical_and_closed() -> None:
    current = json.loads(Path("docs/CURRENT_STATE.json").read_text(encoding="utf-8"))
    assert current["canonical_demo_installation"] == "docs/DEMO_INSTALLATION.md"
    assert "demo_installation_implementation_and_certification" not in current["open_work"]

    makefile = Path("Makefile").read_text(encoding="utf-8")
    for target in (
        "demo-seed:",
        "demo-preflight:",
        "demo-up:",
        "demo-certify:",
        "demo-down:",
        "demo-reset:",
    ):
        assert target in makefile

    base_compose = Path("compose.yml").read_text(encoding="utf-8")
    assert "DOR_API_URL: http://api:8000" in base_compose
    assert "DOR_API_BASE:" not in base_compose

    demo_compose = Path("compose.demo.yml").read_text(encoding="utf-8")
    assert "target: /demo/patch-workspace" in demo_compose
    assert "target: /audit/checkouts" in demo_compose
    assert "read_only: true" in demo_compose
