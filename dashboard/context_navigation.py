"""Persistent organization/project context for the canonical Streamlit GUI."""

from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError

_ALL_PROJECTS = "__all_projects__"
_ORGANIZATION_CATALOG_KEY = "organization_context_catalog"
_PROJECT_CATALOG_KEY = "project_context_catalog"


def normalize_organization_catalog(payload: Any) -> dict[str, Any]:
    """Normalize the authenticated organization catalog."""
    if not isinstance(payload, Mapping):
        return {"active_organization_id": None, "organizations": []}

    active = str(payload.get("active_organization_id") or "").strip() or None
    organizations: list[dict[str, Any]] = []
    raw = payload.get("organizations")
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            organization_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not organization_id or not name:
                continue
            organizations.append(
                {
                    "id": organization_id,
                    "name": name,
                    "description": str(item.get("description") or ""),
                    "is_admin": item.get("is_admin") is True,
                    "created_at": str(item.get("created_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )
    return {
        "active_organization_id": active,
        "organizations": organizations,
    }


def normalize_project_catalog(payload: Any) -> dict[str, Any]:
    """Normalize one explicitly selected tenant-scoped project catalog."""
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


def _clear_execution_context() -> None:
    st.session_state["selected_project_id"] = None
    st.session_state["selected_project_fingerprint"] = None
    st.session_state["selected_workflow_id"] = None
    st.session_state.pop("workflow_input", None)
    st.session_state["realtime_workflow_id"] = None
    st.session_state["realtime_status"] = "offline"


def _project_catalog(
    client: DORAPIClient, organization_id: str | None
) -> dict[str, Any]:
    if not organization_id:
        return {"organization_id": None, "projects": []}
    return normalize_project_catalog(
        client.get(
            "/api/v1/control-plane/projects",
            params={"organization_id": organization_id},
        )
    )


def sync_organization_context(client: DORAPIClient) -> dict[str, Any]:
    """Refresh accessible organizations and the active organization's projects."""
    organizations = normalize_organization_catalog(
        client.get("/api/v1/control-plane/organizations")
    )
    st.session_state[_ORGANIZATION_CATALOG_KEY] = organizations
    available_ids = [item["id"] for item in organizations["organizations"]]

    current = st.session_state.get("organization_id")
    if current not in available_ids:
        default = organizations.get("active_organization_id")
        current = (
            default
            if default in available_ids
            else (available_ids[0] if available_ids else None)
        )
        if current != st.session_state.get("organization_id"):
            _clear_execution_context()
        st.session_state["organization_id"] = current

    catalog = _project_catalog(client, current)
    st.session_state[_PROJECT_CATALOG_KEY] = catalog
    selected_project = st.session_state.get("selected_project_id")
    project_ids = {item["project_id"] for item in catalog["projects"]}
    if selected_project is not None and selected_project not in project_ids:
        st.session_state["selected_project_id"] = None
        st.session_state["selected_project_fingerprint"] = None
        st.session_state["selected_workflow_id"] = None
    return catalog


def render_sidebar_organization_switcher(client: DORAPIClient) -> None:
    """Render the active organization selector on every authenticated GUI page."""
    catalog = st.session_state.get(_ORGANIZATION_CATALOG_KEY)
    if not isinstance(catalog, Mapping):
        try:
            sync_organization_context(client)
        except DORAPIError:
            return
        catalog = st.session_state.get(_ORGANIZATION_CATALOG_KEY)
    if not isinstance(catalog, Mapping):
        return

    organizations_value = catalog.get("organizations")
    organizations = (
        organizations_value if isinstance(organizations_value, list) else []
    )
    if not organizations:
        st.sidebar.warning("Ingen organisationer er knyttet til din bruger.")
        return

    by_id = {item["id"]: item for item in organizations}
    options = list(by_id)
    current = st.session_state.get("organization_id")
    index = options.index(current) if current in options else 0
    selected = st.sidebar.selectbox(
        "Aktiv organisation",
        options,
        index=index,
        format_func=lambda value: f"{by_id[value]['name']} · {value}",
        key="active_organization_selector",
        help="Kun organisationer, som backend har knyttet til din bruger, vises her.",
    )
    if selected != current:
        st.session_state["organization_id"] = selected
        _clear_execution_context()
        st.session_state[_PROJECT_CATALOG_KEY] = _project_catalog(client, selected)


def _render_organization_management(client: DORAPIClient) -> None:
    catalog = st.session_state.get(_ORGANIZATION_CATALOG_KEY)
    organizations = (
        catalog.get("organizations", []) if isinstance(catalog, Mapping) else []
    )
    by_id = {
        item["id"]: item
        for item in organizations
        if isinstance(item, Mapping) and item.get("id")
    }
    active_id = st.session_state.get("organization_id")
    active = by_id.get(active_id)

    with st.expander("Administrer organisationer", expanded=not bool(organizations)):
        st.markdown("#### Opret organisation")
        with st.form("organization_create_form", clear_on_submit=True):
            organization_id = st.text_input(
                "ID",
                help="Permanent teknisk ID, fx `acme-platform`. Kan ikke omdøbes senere.",
            )
            name = st.text_input("Navn")
            description = st.text_area("Beskrivelse")
            create = st.form_submit_button("Opret organisation", type="primary")
        if create:
            try:
                created = client.post(
                    "/api/v1/control-plane/organizations",
                    json={
                        "id": organization_id.strip(),
                        "name": name.strip(),
                        "description": description.strip(),
                    },
                )
                st.session_state["organization_id"] = created["id"]
                _clear_execution_context()
                st.session_state.pop(_ORGANIZATION_CATALOG_KEY, None)
                st.session_state.pop(_PROJECT_CATALOG_KEY, None)
                st.success(f"Organisation `{created['name']}` blev oprettet.")
                st.rerun()
            except DORAPIError as exc:
                st.error(
                    f"Organisation kunne ikke oprettes ({exc.status_code}): {exc}"
                )

        if active is None:
            return
        if active.get("is_admin") is not True:
            st.caption(
                "Du kan vælge organisationen, men har ikke admin-ret til at omdøbe den."
            )
            return

        st.divider()
        st.markdown("#### Omdøb / redigér aktiv organisation")
        st.caption(f"Det permanente ID er `{active['id']}`.")
        with st.form(f"organization_update_form_{active['id']}"):
            updated_name = st.text_input(
                "Navn", value=str(active.get("name") or "")
            )
            updated_description = st.text_area(
                "Beskrivelse",
                value=str(active.get("description") or ""),
            )
            update = st.form_submit_button("Gem ændringer")
        if update:
            try:
                updated = client.patch(
                    f"/api/v1/control-plane/organizations/{active['id']}",
                    json={
                        "name": updated_name.strip(),
                        "description": updated_description.strip(),
                    },
                )
                st.session_state.pop(_ORGANIZATION_CATALOG_KEY, None)
                st.success(f"Organisation `{updated['name']}` blev opdateret.")
                st.rerun()
            except DORAPIError as exc:
                st.error(
                    f"Organisation kunne ikke opdateres ({exc.status_code}): {exc}"
                )


def render_context_navigation(client: DORAPIClient) -> dict[str, Any]:
    """Render Organization -> Project -> Execution context from backend state once."""
    st.subheader("🧭 Arbejdskontekst")
    try:
        catalog = sync_organization_context(client)
    except DORAPIError as exc:
        if exc.status_code == 401:
            raise
        st.warning(f"Organisationskatalog ikke tilgængeligt ({exc.status_code}): {exc}")
        organization_id = st.session_state.get("organization_id")
        catalog = {"organization_id": organization_id, "projects": []}
        st.session_state[_PROJECT_CATALOG_KEY] = catalog

    render_sidebar_organization_switcher(client)
    _render_organization_management(client)

    organization_id = st.session_state.get("organization_id")
    cached_catalog = st.session_state.get(_PROJECT_CATALOG_KEY)
    if (
        isinstance(cached_catalog, Mapping)
        and cached_catalog.get("organization_id") == organization_id
    ):
        catalog = cached_catalog
    elif organization_id:
        try:
            catalog = _project_catalog(client, organization_id)
            st.session_state[_PROJECT_CATALOG_KEY] = catalog
        except DORAPIError as exc:
            if exc.status_code == 401:
                raise
            st.warning(f"Projektkatalog ikke tilgængeligt ({exc.status_code}): {exc}")
            catalog = {"organization_id": organization_id, "projects": []}
    else:
        catalog = {"organization_id": None, "projects": []}

    projects_value = catalog.get("projects")
    projects = projects_value if isinstance(projects_value, list) else []
    by_id = {item["project_id"]: item for item in projects}
    current_project_id = st.session_state.get("selected_project_id")

    options = [_ALL_PROJECTS, *by_id]
    index = options.index(current_project_id) if current_project_id in options else 0

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
        help="Projektlisten kommer fra den valgte authenticated organisation.",
    )
    selected_project_id = (
        None if selected_value == _ALL_PROJECTS else selected_value
    )

    if selected_project_id != current_project_id:
        st.session_state["selected_project_id"] = selected_project_id
        selected_project = by_id.get(selected_project_id or "")
        st.session_state["selected_project_fingerprint"] = (
            selected_project.get("project_fingerprint") if selected_project else None
        )
        st.session_state["selected_workflow_id"] = None
        st.session_state.pop("workflow_input", None)
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
        st.caption("Ingen læsbare projekter i den aktive organisation.")

    return {
        "organization_id": organization_id,
        "selected_project_id": selected_project_id,
        "selected_project_name": selected_project_name,
        "projects": projects,
    }
