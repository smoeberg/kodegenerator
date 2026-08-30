"""Unit tests for the Phase 7 platform-skip manifest verifier."""

from __future__ import annotations

import json

import pytest

from ci.verify_platform_skips import (
    REPO_ROOT,
    load_json,
    render_summary,
    validate_environments,
    validate_ids,
    validate_test_paths,
)

MANIFEST = REPO_ROOT / "ci" / "manifests" / "platform_skips.json"


@pytest.fixture()
def manifest() -> dict:
    return load_json(MANIFEST)


def test_manifest_exists_and_is_valid_json(manifest: dict) -> None:
    assert manifest["version"] == 1
    assert manifest["schema"].startswith("https://")


def test_skip_ids_are_unique_and_sequential(manifest: dict) -> None:
    assert validate_ids(manifest) == []


def test_test_paths_unique_per_environment(manifest: dict) -> None:
    assert validate_test_paths(manifest) == []


def test_same_test_may_be_listed_for_distinct_environments(manifest: dict) -> None:
    """A sandbox file can have one entry per environment signal (auto-heal + integration)."""
    variant = json.loads(json.dumps(manifest))
    variant["skips"].append(
        {
            "id": "env-99",
            "reason": "sandbox integration variant on the dedicated runner",
            "test_ids": ["tests/phase6/test_process_sandbox.py"],
            "environment": "integration",
            "type": "integration-only",
            "owner": "chore",
        }
    )
    assert validate_test_paths(variant) == []


def test_duplicate_test_path_same_environment_is_rejected(manifest: dict) -> None:
    broken = json.loads(json.dumps(manifest))
    broken["skips"][0]["test_ids"] = broken["skips"][1]["test_ids"]
    assert validate_test_paths(broken) != []


def test_e2e_tests_map_only_to_integration_runner(manifest: dict) -> None:
    for entry in manifest["skips"]:
        if any(t.startswith("tests/e2e/") for t in entry["test_ids"]):
            assert entry["environment"] == "integration"


def test_environments_resolve(manifest: dict) -> None:
    assert validate_environments(manifest) == []
    assert "integration" in {env["id"] for env in manifest["environments"]}


def test_unknown_environment_is_rejected(manifest: dict) -> None:
    broken = json.loads(json.dumps(manifest))
    broken["skips"][0]["environment"] = "no-such-env"
    assert validate_environments(broken) != []


def test_duplicate_test_path_is_rejected(manifest: dict) -> None:
    broken = json.loads(json.dumps(manifest))
    broken["skips"][0]["test_ids"] = broken["skips"][1]["test_ids"]
    assert validate_test_paths(broken) != []


def test_duplicate_env_id_is_rejected(manifest: dict) -> None:
    broken = json.loads(json.dumps(manifest))
    broken["skips"][0]["id"] = broken["skips"][1]["id"]
    errors = validate_ids(broken)
    assert any("duplicate" in error for error in errors)


def test_summary_renders_all_entries(manifest: dict) -> None:
    summary = render_summary(manifest)
    assert "Manifest version: 1" in summary
    for entry in manifest["skips"]:
        assert entry["id"] in summary


def test_stray_manifest_missing_id_fails() -> None:
    """Guard: a skip without an id must never pass."""
    broken = json.loads(json.dumps(load_json(MANIFEST)))
    del broken["skips"][0]["id"]
    # The check itself is defensive: validation should surface a KeyError.
    with pytest.raises(KeyError):
        validate_ids(broken)
