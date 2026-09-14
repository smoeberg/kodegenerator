"""Surface tests for backend-authorized pipeline requirements editing."""
from __future__ import annotations

from pathlib import Path

import yaml

MODULE = Path("dashboard/pipeline_requirements_forms.py").read_text(encoding="utf-8")
APP = Path("dashboard/app.py").read_text(encoding="utf-8")


def test_editor_uses_typed_api_resources_only() -> None:
    """The editor must only touch the typed pipeline requirements endpoints."""
    assert "/api/v1/pipeline" in MODULE
    assert "get(" in MODULE and "put(" in MODULE
    assert "SELECT" not in MODULE.upper() and "sqlite" not in MODULE.lower()


def test_essential_fields_are_locked() -> None:
    """Essential identity fields render disabled and are never edited."""
    assert "project_name" in MODULE and "project_description" in MODULE
    assert "disabled=True" in MODULE
    for locked in ("project_name", "project_description"):
        assert f'"{locked}"' in MODULE.split("editable_fields:")[0]


def test_editing_allowed_only_before_gate_approval() -> None:
    """is_editable gates on DRAFT/VALIDATED states only."""
    assert '("REQUIREMENTS_DRAFT", "REQUIREMENTS_VALIDATED")' in MODULE


def test_save_overwrites_full_spec_via_put() -> None:
    """Saving serializes the whole spec as YAML for the PUT payload."""
    assert "requirements_yaml" in MODULE
    assert "yaml.safe_dump" in MODULE and "yaml.safe_load" in MODULE


def test_fetch_parses_yaml_to_mapping() -> None:
    """fetch_requirements returns a dict parsed from the API YAML."""
    text = MODULE
    assert "yaml.safe_load" in text.split("def save_requirements")[0]


def test_app_integrates_requirements_editor() -> None:
    """The project page renders the editor under Logik 1."""
    assert "render_requirements_editor" in APP
    assert "Pipeline Workflow ID (kravredigering)" in APP
    assert "kravredigering" in APP


def test_roundtrip_spec_yaml() -> None:
    """The dumped spec round-trips through yaml and keeps field order."""
    spec = {"project_name": "X", "project_description": "D", "priority": "high"}
    dumped = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)
    assert list(yaml.safe_load(dumped)) == list(spec)
