"""Executable syntax and example checks for the multi-bot factory contracts."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "docs" / "schemas"
EXAMPLES = SCHEMAS / "examples"
ARCHITECTURE = ROOT / "docs" / "architecture"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_bot_governance_example_conforms_to_schema() -> None:
    schema = _load(SCHEMAS / "bot-governance-v1.schema.json")
    example = _load(EXAMPLES / "bot-governance-v1.example.json")

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)


def test_factory_work_package_example_conforms_to_schema() -> None:
    schema = _load(SCHEMAS / "factory-work-package-v1.schema.json")
    example = _load(EXAMPLES / "factory-work-package-v1.example.json")

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(example)


def test_role_contracts_are_provider_neutral() -> None:
    example = _load(EXAMPLES / "bot-governance-v1.example.json")
    provider_names = {connection["brand"] for connection in example["connections"]}

    for role in example["roles"]:
        encoded = json.dumps(role, sort_keys=True).lower()
        assert all(brand.lower() not in encoded for brand in provider_names)


def test_allocations_reference_declared_bot_profiles() -> None:
    example = _load(EXAMPLES / "bot-governance-v1.example.json")
    profile_ids = {profile["bot_profile_id"] for profile in example["bot_profiles"]}

    for allocation in example["allocations"]:
        allowed = set(allocation["allowed_bot_profile_ids"])
        preferred = set(allocation["preferred_bot_profile_ids"])
        assert allowed <= profile_ids
        assert preferred <= allowed


def test_council_templates_reference_declared_roles_and_matching_functions() -> None:
    example = _load(EXAMPLES / "bot-governance-v1.example.json")
    roles = {role["role_id"]: role for role in example["roles"]}

    for template in example["council_templates"]:
        for stage in template["stages"]:
            for role_id in stage["role_ids"]:
                assert role_id in roles
                assert roles[role_id]["protocol_function"] == stage["protocol_function"]
                assert stage["minimum_assignments"] <= stage["maximum_assignments"]


def test_execution_plan_has_no_unresolved_implementation_placeholders() -> None:
    plan = (
        ARCHITECTURE / "GOVERNED_MULTI_BOT_FACTORY_EXECUTION_PLAN_V1.md"
    ).read_text(encoding="utf-8")

    assert "TODO" not in plan
    assert "pass  #" not in plan
    assert "services/git_publisher.py" not in plan
    assert "services/git_pr_publisher.py" in plan


def test_execution_plan_preserves_linear_migration_sequence() -> None:
    plan = (
        ARCHITECTURE / "GOVERNED_MULTI_BOT_FACTORY_EXECUTION_PLAN_V1.md"
    ).read_text(encoding="utf-8")

    revisions = [
        "018_bot_catalog",
        "019_council_configuration",
        "020_bot_selection_assignments",
        "021_bot_evaluation_performance",
        "022_factory_work_candidates",
        "023_factory_integration",
    ]
    positions = [plan.index(revision) for revision in revisions]
    assert positions == sorted(positions)
