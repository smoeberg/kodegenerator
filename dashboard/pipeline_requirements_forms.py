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

# Fields the backend treats as the essential identity of one requirement line.
ESSENTIAL_LINE_FIELDS = frozenset({"id", "description", "acceptance_criteria"})


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


LINE_KEY = "selected_requirement_index"


def render_requirements_editor(
    client: DORAPIClient, workflow_id: str, org_id: str, state: str
) -> None:
    """List the requirements; open one line in a form; edit and save."""
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

    requirements = spec.get("requirements")
    if not isinstance(requirements, list) or not requirements:
        st.error("Specifikationen indeholder ingen kravlinjer.")
        return

    st.caption(
        "Klik på en kravlinje for at åbne den i formularen, rediger de "
        "ikke-essentielle felter og gem. Ved gem overskrives specifikationen via API'et."
    )

    import pandas as pd

    table = pd.DataFrame(
        [
            {
                "Linje": idx,
                "ID": str(req.get("id", "")),
                "Beskrivelse": str(req.get("description", "")),
                "Ikke-essentielle": ", ".join(
                    f"{k}" for k in sorted(req) if k not in ESSENTIAL_LINE_FIELDS
                ),
            }
            for idx, req in enumerate(requirements)
        ]
    )
    event = st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key="requirement_list",
    )
    if event.selection.rows:
        selected = int(event.selection.rows[0])
        st.session_state[LINE_KEY] = selected
        _render_requirement_form(client, workflow_id, org_id, spec, requirements, selected)
    elif LINE_KEY in st.session_state:
        selected = int(st.session_state[LINE_KEY])
        if 0 <= selected < len(requirements):
            _render_requirement_form(client, workflow_id, org_id, spec, requirements, selected)
    _render_spec_level_editor(client, workflow_id, org_id, spec)


def _render_requirement_form(
    client: DORAPIClient,
    workflow_id: str,
    org_id: str,
    spec: dict[str, Any],
    requirements: list[Any],
    index: int,
) -> None:
    """Edit one requirement line: essential fields locked, others editable."""
    req = requirements[index]
    st.subheader(f"Krav {req.get('id', index)}")
    with st.form(f"requirement_form_{index}"):
        st.text_input("id (låst)", value=str(req.get("id", "")), disabled=True)
        st.text_area(
            "description (låst)",
            value=str(req.get("description", "")),
            disabled=True,
        )
        st.text_area(
            "acceptance_criteria (låst)",
            value=str(req.get("acceptance_criteria", "")),
            disabled=True,
        )
        editable: dict[str, str] = {}
        for key in sorted(k for k in req if k not in ESSENTIAL_LINE_FIELDS):
            value = req[key]
            if isinstance(value, (dict, list)):
                rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=False).strip()
                editable[key] = st.text_area(key, value=rendered, height=100)
            else:
                editable[key] = st.text_input(key, value=str(value))
        if not st.form_submit_button("Gem linje"):
            return
    new_req = dict(req)
    for key, value in editable.items():
        if not value.strip():
            continue
        try:
            new_req[key] = yaml.safe_load(value)
        except yaml.YAMLError:
            new_req[key] = value
    new_spec = dict(spec)
    new_requirements = list(requirements)
    new_requirements[index] = new_req
    new_spec["requirements"] = new_requirements
    _save_spec(client, workflow_id, org_id, spec, new_spec)


def _render_spec_level_editor(
    client: DORAPIClient, workflow_id: str, org_id: str, spec: dict[str, Any]
) -> None:
    """Edit the spec-level non-essential fields (project identity is locked)."""
    with st.expander("Spec-niveau felter"):
        with st.form("spec_level_form"):
            st.text_input(
                "project_name (låst)",
                value=str(spec.get("project_name", "")),
                disabled=True,
            )
            st.text_area(
                "project_description (låst)",
                value=str(spec.get("project_description", "")),
                disabled=True,
            )
            editable: dict[str, str] = {}
            for key in sorted(k for k in spec if k not in ESSENTIAL_FIELDS):
                if key == "requirements":
                    continue
                value = spec[key]
                if isinstance(value, (dict, list)):
                    rendered = yaml.safe_dump(
                        value, allow_unicode=True, sort_keys=False
                    ).strip()
                    editable[key] = st.text_area(key, value=rendered, height=100)
                else:
                    editable[key] = st.text_input(key, value=str(value))
            if not st.form_submit_button("Gem spec-niveau"):
                return
    new_spec = dict(spec)
    for key, value in editable.items():
        if not value.strip():
            continue
        try:
            new_spec[key] = yaml.safe_load(value)
        except yaml.YAMLError:
            new_spec[key] = value
    _save_spec(client, workflow_id, org_id, spec, new_spec)


def _save_spec(
    client: DORAPIClient,
    workflow_id: str,
    org_id: str,
    old_spec: dict[str, Any],
    new_spec: dict[str, Any],
) -> None:
    """PUT the full spec and report the outcome."""
    if new_spec == old_spec:
        st.info("Ingen ændringer at gemme.")
        return
    try:
        save_requirements(client, workflow_id, org_id, new_spec)
    except DORAPIError as exc:
        st.error(f"API afviste gem ({exc.status_code}): {exc}")
        return
    st.success("Krav gemt — specifikationen er overskrevet via API'et.")
    st.rerun()
