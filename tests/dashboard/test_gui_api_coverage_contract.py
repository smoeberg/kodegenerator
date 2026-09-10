"""Contract tests for canonical GUI coverage of the mounted API surface."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INVENTORY_PATH = ROOT / "docs" / "api-endpoint-inventory.json"
COVERAGE_PATH = ROOT / "docs" / "gui-api-coverage.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _key(item: dict) -> tuple[str, str]:
    return str(item["method"]), str(item["path"])


def test_every_mounted_endpoint_has_exactly_one_gui_classification() -> None:
    inventory = _load(INVENTORY_PATH)
    coverage = _load(COVERAGE_PATH)

    inventory_keys = [_key(item) for item in inventory["endpoints"]]
    coverage_keys = [_key(item) for item in coverage["endpoints"]]

    assert len(inventory_keys) == inventory["count"]
    assert len(inventory_keys) == len(set(inventory_keys))
    assert len(coverage_keys) == len(set(coverage_keys))
    assert set(coverage_keys) == set(inventory_keys)


def test_coverage_summary_is_derived_from_classifications() -> None:
    coverage = _load(COVERAGE_PATH)
    counts = Counter(item["status"] for item in coverage["endpoints"])

    assert coverage["summary"] == {
        "total": len(coverage["endpoints"]),
        "covered": counts["covered"],
        "planned": counts["planned"],
        "internal": counts["internal"],
    }
    assert coverage["summary"] == {
        "total": 104,
        "covered": 64,
        "planned": 15,
        "internal": 25,
    }


def test_surface_and_status_contract_is_fail_closed() -> None:
    coverage = _load(COVERAGE_PATH)
    allowed_surfaces = {"sag", "soeg", "administration", "internal"}
    allowed_statuses = {"covered", "planned", "internal"}

    for item in coverage["endpoints"]:
        assert item["surface"] in allowed_surfaces
        assert item["status"] in allowed_statuses
        assert str(item["capability"]).strip()
        if item["status"] == "internal":
            assert item["surface"] == "internal"
        else:
            assert item["surface"] != "internal"


def test_user_relevant_gaps_are_explicit_not_silently_internal() -> None:
    coverage = _load(COVERAGE_PATH)
    by_key = {_key(item): item for item in coverage["endpoints"]}

    required_planned = {
        ("POST", "/api/v1/control-plane/artifact-acceptances"),
        ("POST", "/api/v1/control-plane/delivery-certificates"),
        ("POST", "/api/v1/control-plane/requirement-traceability"),
        ("POST", "/api/v1/decisions"),
        ("GET", "/api/v1/decisions/{decision_id}"),
        ("POST", "/api/v1/execution/start"),
    }

    for key in required_planned:
        assert by_key[key]["status"] == "planned"
        assert by_key[key]["surface"] == "sag"


def test_case_clarification_and_decision_resolution_are_covered_in_sag() -> None:
    coverage = _load(COVERAGE_PATH)
    by_key = {_key(item): item for item in coverage["endpoints"]}
    keys = {
        ("POST", "/api/v1/control-plane/onboarding-intents"),
        ("GET", "/api/v1/control-plane/onboarding-intents/current"),
        ("GET", "/api/v1/decisions/pending"),
        ("POST", "/api/v1/decisions/{decision_id}/resolve"),
    }

    for key in keys:
        assert by_key[key]["status"] == "covered"
        assert by_key[key]["surface"] == "sag"


def test_system_ai_settings_are_covered_in_administration() -> None:
    coverage = _load(COVERAGE_PATH)
    by_key = {_key(item): item for item in coverage["endpoints"]}
    keys = {
        ("GET", "/api/v1/integrations/ai/config"),
        ("PUT", "/api/v1/integrations/ai/config"),
        ("POST", "/api/v1/integrations/ai/test"),
    }
    for key in keys:
        assert by_key[key]["status"] == "covered"
        assert by_key[key]["surface"] == "administration"


def test_worker_and_legacy_protocols_remain_internal() -> None:
    coverage = _load(COVERAGE_PATH)
    by_key = {_key(item): item for item in coverage["endpoints"]}

    internal_keys = {
        ("POST", "/api/v1/swarm/workers/claim"),
        ("POST", "/api/v1/swarm/workers/complete"),
        ("POST", "/api/v1/swarm/workers/heartbeat"),
        ("POST", "/pipeline/{workflow_id}/advance"),
        ("POST", "/workflows/{workflow_id}/transition"),
        ("GET", "/protected"),
    }

    for key in internal_keys:
        assert by_key[key]["status"] == "internal"
        assert by_key[key]["surface"] == "internal"
