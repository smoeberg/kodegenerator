"""Persistent organization/project context for the canonical Streamlit GUI."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError

_ALL_PROJECTS = "__all_projects__"
_CATALOG_STATE_KEY = "project_context_catalog"


def normalize_project_catalog(payload: Any) -> dict[str, Any]:
    """Normalize the tenant-scoped Control Plane project catalog."""
    if not isinstance(payload, Mapping):
        return {"organization_id": None, "projects": []}

    organization_id = str(payload.get("organization_id") or "").strip() or None
    raw_projects = payload.get("projects")
    projects: list[dict[str, Any]] = []
    if isinstance(raw_projects, list):
        for item in raw_projects:
            if not isinstance(item, Mapping):
                continue
            project_id = str(item.get("project_id") or "").strip()
            if not project_id:
                continue
            projects.append(
                {
                    "project_id": project_id,
                    "organization_id": str(
                        item.get("organization_id") or organization_id or ""
                    ).strip()
                    or None,
                    "name": str(item.get("name") or project_id),
                    "status": str(item.get("status") or "unknown"),
                    "project_fingerprint": str(
                        item.get("project_fingerprint") or ""
                    ).strip()
                    or None,
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )

    return {"organization_id": organization_id, "projects": projects}


def sync_organization_context(client: DORAPIClient) -> dict[str, Any]:
    """Refresh the authenticated tenant/project catalog once per app rerun."""
    catalog = normalize_project_catalog(client.get("/api/v1/control-plane/projects"))
    st.session_state[_CATALOG_STATE_KEY] = catalog
    organization_id = catalog["organization_id"]
    if organization_id:
        st.session_state["organization_id"] = organization_id
    return catalog


def _clear_execution_context() -> None:
    st.session_state["selected_workflow_id"] = None
    st.session_state.pop("workflow_input", None)
    st.session_state["realtime_workflow_id"] = None
    st.session_state["realtime_status"] = "offline"


def render_context_navigation(client: DORAPIClient) -> dict[str, Any]:
    """Render Organization -> Project -> Execution context from backend state."""
    st.subheader("🧭 Arbejdskontekst")

    catalog = st.session_state.get(_CATALOG_STATE_KEY)
    if not isinstance(catalog, Mapping):
        try:
            catalog = sync_organization_context(client)
        except DORAPIError as exc:
            if exc.status_code == 401:
                raise
            st.warning(
                f"Projektkatalog ikke tilgængeligt ({exc.status_code}): {exc}. "
                "Manuel cockpit-fallback er fortsat tilgængelig."
            )
            catalog = {
                "organization_id": st.session_state.get("organization_id"),
                "projects": [],
            }
        except Exception as exc:
            st.warning(
                f"Projektkatalog ikke tilgængeligt: {exc}. "
                "Manuel cockpit-fallback er fortsat tilgængelig."
            )
            catalog = {
                "organization_id": st.session_state.get("organization_id"),
                "projects": [],
            }

    organization_id = catalog.get("organization_id")
    if organization_id:
        st.session_state["organization_id"] = organization_id

    projects_value = catalog.get("projects")
    projects = projects_value if isinstance(projects_value, list) else []
    by_id = {item["project_id"]: item for item in projects}
    current_project_id = st.session_state.get("selected_project_id")

    options = [_ALL_PROJECTS, *by_id]
    index = (
        options.index(current_project_id)
        if current_project_id in options
        else 0
    )

    def format_project(value: str) -> str:
        if value == _ALL_PROJECTS:
            return "Alle projekter"
        project = by_id[value]
        return f"{project['name']} · {project['status']}"

    selected_value = st.selectbox(
        "Projekt",
        options,
        index=index,
        format_func=format_project,
        help=(
            "Projektlisten kommer fra den authenticated Control Plane API. "
            "Executions filtreres kun på eksplicit backend project_id."
        ),
    )
    selected_project_id = (
        None if selected_value == _ALL_PROJECTS else selected_value
    )

    if selected_project_id != current_project_id:
        st.session_state["selected_project_id"] = selected_project_id
        selected_project = by_id.get(selected_project_id or "")
        st.session_state["selected_project_fingerprint"] = (
            selected_project.get("project_fingerprint")
            if selected_project
            else None
        )
        _clear_execution_context()
    else:
        selected_project = by_id.get(selected_project_id or "")
        if selected_project:
            st.session_state["selected_project_fingerprint"] = selected_project.get(
                "project_fingerprint"
            )

    selected_project_name = (
        selected_project["name"] if selected_project else "Alle projekter"
    )
    workflow_id = st.session_state.get("selected_workflow_id") or "—"
    st.caption(
        " › ".join(
            [
                f"Organisation `{organization_id or '—'}`",
                f"Projekt `{selected_project_name}`",
                f"Execution `{workflow_id}`",
            ]
        )
    )

    if not projects:
        st.caption("Ingen læsbare projekter rapporteret af Control Plane API.")

    return {
        "organization_id": organization_id,
        "selected_project_id": selected_project_id,
        "selected_project_name": selected_project_name,
        "projects": projects,
    }
