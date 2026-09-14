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
    assert "SELECT " not in MODULE and "sqlite" not in MODULE.lower()


def test_essential_fields_are_locked() -> None:
    """Spec-level and line-level essential fields render disabled."""
    assert 'ESSENTIAL_LINE_FIELDS = frozenset({"id", "description", "acceptance_criteria"})' in MODULE
    for locked in ("project_name", "project_description", "id", "description", "acceptance_criteria"):
        assert f'"{locked} (låst)"' in MODULE


def test_editing_allowed_only_before_gate_approval() -> None:
    """is_editable gates on DRAFT/VALIDATED states only."""
    assert '("REQUIREMENTS_DRAFT", "REQUIREMENTS_VALIDATED")' in MODULE


def test_save_overwrites_full_spec_via_put() -> None:
    """Saving serializes the whole spec as YAML for the PUT payload."""
    assert "requirements_yaml" in MODULE
    assert "yaml.safe_dump" in MODULE and "yaml.safe_load" in MODULE


def test_list_view_is_clickable_dataframe() -> None:
    """The list view is an interactive table; clicking a row selects it."""
    assert "st.dataframe(" in MODULE
    assert 'on_select="rerun"' in MODULE
    assert 'selection_mode="single-row"' in MODULE
    assert "event.selection.rows" in MODULE


def test_selected_line_opens_in_form() -> None:
    """A clicked row renders the line in its own form with locked essentials."""
    assert "_render_requirement_form" in MODULE
    assert 'f"requirement_form_{index}"' in MODULE


def test_save_single_line_only_touches_that_line() -> None:
    """Saving a line overwrites only the edited line, not the rest."""
    assert "new_requirements[index] = new_req" in MODULE
    assert "new_requirements = list(requirements)" in MODULE


def test_app_integrates_requirements_editor() -> None:
    """The project page renders the editor under Logik 1."""
    assert "render_requirements_editor" in APP
    assert "Pipeline Workflow ID (kravredigering)" in APP


def test_roundtrip_spec_yaml() -> None:
    """The dumped spec round-trips through yaml and keeps field order."""
    spec = {"project_name": "X", "project_description": "D", "priority": "high"}
    dumped = yaml.safe_dump(spec, allow_unicode=True, sort_keys=False)
    assert list(yaml.safe_load(dumped)) == list(spec)
