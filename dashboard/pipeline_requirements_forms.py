"""Backend-authorized pipeline requirements editing.

Presents the requirements spec of a pipeline as editable lines in the
operator GUI. Each line is fetched through the typed API, non-essential
fields are editable, and saving overwrites the spec via PUT. The backend
keeps ownership of validation and the requirements-gate rule: after the
gate is approved, editing is rejected.
"""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st
import yaml

from dashboard.api_client import DORAPIClient, DORAPIError

REQUIREMENTS_PATH = "/api/v1/pipeline"

# Fields the backend treats as the essential identity of the spec.
ESSENTIAL_FIELDS = frozenset({"project_name", "project_description"})


def fetch_requirements(client: DORAPIClient, workflow_id: str, org_id: str) -> dict[str, Any]:
    """GET the requirements YAML and parse it into a spec dict."""
    response = client.get(
        f"{REQUIREMENTS_PATH}/{workflow_id}/requirements",
        params={"organization_id": org_id},
    )
    raw = response.get("requirements_yaml")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("API returned no requirements YAML")
    spec = yaml.safe_load(raw)
    if not isinstance(spec, dict):
        raise ValueError("Requirements YAML did not parse to a mapping")
    return spec


def save_requirements(
    client: DORAPIClient, workflow_id: str, org_id: str, spec: Mapping[str, Any]
) -> dict[str, Any]:
    """PUT the full spec; the backend validates and enforces the gate rule."""
    response = client.put(
        f"{REQUIREMENTS_PATH}/{workflow_id}/requirements",
        params={"organization_id": org_id},
        json={"requirements_yaml": yaml.safe_dump(dict(spec), allow_unicode=True, sort_keys=False)},
    )
    raw = response.get("requirements_yaml")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("API returned no requirements YAML")
    saved = yaml.safe_load(raw)
    if not isinstance(saved, dict):
        raise ValueError("Requirements YAML did not parse to a mapping")
    return saved


def is_editable(state: str) -> bool:
    """Non-essential editing is allowed until the requirements gate is approved."""
    return state in ("REQUIREMENTS_DRAFT", "REQUIREMENTS_VALIDATED")


def render_requirements_editor(
    client: DORAPIClient, workflow_id: str, org_id: str, state: str
) -> None:
    """Render the requirements spec as editable lines."""
    if not is_editable(state):
        st.info(
            "Kravene er låst: requirements-gaten er godkendt. "
            "Opret en ny pipeline for at redigere kravene."
        )
        return
    try:
        spec = fetch_requirements(client, workflow_id, org_id)
    except (DORAPIError, ValueError) as exc:
        st.error(f"Kunne ikke hente krav: {exc}")
        return

    st.caption(
        "Essentielle felter er låst. Rediger de øvrige felter og gem. "
        "Ved gem overskrives hele krav-specifikationen via API'et."
    )

    with st.form("pipeline_requirements_form"):
        project_name = st.text_input(
            "Projektnavn (låst)", value=str(spec.get("project_name", "")), disabled=True
        )
        project_description = st.text_area(
            "Projektbeskrivelse (låst)",
            value=str(spec.get("project_description", "")),
            disabled=True,
        )
        editable_fields: dict[str, str] = {}
        for key in sorted(k for k in spec if k not in ESSENTIAL_FIELDS):
            value = spec[key]
            if isinstance(value, (dict, list)):
                rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
                editable_fields[key] = st.text_area(key, value=rendered, height=120)
            else:
                editable_fields[key] = st.text_input(key, value=str(value))
        saved = st.form_submit_button("Gem krav")

    if not saved:
        return
    new_spec = dict(spec)
    for key, value in editable_fields.items():
        if not value.strip():
            new_spec[key] = spec[key]
            continue
        try:
            new_spec[key] = yaml.safe_load(value)
        except yaml.YAMLError:
            new_spec[key] = value
    try:
        save_requirements(client, workflow_id, org_id, new_spec)
    except DORAPIError as exc:
        st.error(f"API afviste gem ({exc.status_code}): {exc}")
        return
    st.success("Krav gemt — specifikationen er overskrevet via API'et.")
    st.rerun()
