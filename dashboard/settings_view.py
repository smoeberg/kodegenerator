"""Unified, human-facing Administration / Settings workspace."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
from dashboard.redmine_integration import render_redmine_integration


def _human_error(exc: DORAPIError, action: str) -> str:
    if exc.status_code == 403:
        return f"Du har ikke administratorrettigheder til at {action}."
    if exc.status_code == 409:
        return f"DOR kunne ikke {action}, fordi oplysningerne konflikter med den aktuelle opsætning."
    if exc.status_code == 422:
        return "Kontrollér felterne. En eller flere værdier er ugyldige."
    if exc.status_code == 503:
        return f"DOR kan ikke {action} lige nu, fordi en nødvendig systemtjeneste ikke er klar."
    return f"DOR kunne ikke {action} lige nu (fejlkode {exc.status_code})."


def _organization_catalog(client: DORAPIClient) -> dict[str, Any]:
    payload = client.get("/api/v1/control-plane/organizations")
    return dict(payload) if isinstance(payload, Mapping) else {}


def _render_organization_settings(client: DORAPIClient) -> None:
    st.markdown("### Organisation")
    st.caption("Opret og redigér organisationer her. Det tekniske ID vælges én gang ved oprettelse og forbliver stabilt.")
    try:
        catalog = _organization_catalog(client)
    except DORAPIError as exc:
        st.error(_human_error(exc, "hente organisationerne"))
        return

    organizations = [
        dict(item)
        for item in catalog.get("organizations", [])
        if isinstance(item, Mapping)
    ]
    active_id = str(st.session_state.get("organization_id") or "")
    active = next((item for item in organizations if item.get("id") == active_id), None)

    with st.expander("Opret ny organisation", expanded=not organizations):
        with st.form("settings-create-organization", clear_on_submit=True):
            organization_id = st.text_input(
                "Organisationens ID",
                placeholder="min-organisation",
                help="Stabilt ID til DOR. Kan ikke omdøbes efter oprettelse.",
            )
            name = st.text_input("Navn")
            description = st.text_area("Beskrivelse")
            submitted = st.form_submit_button("Opret organisation", type="primary")
        if submitted:
            try:
                created = client.post(
                    "/api/v1/control-plane/organizations",
                    json={
                        "id": organization_id.strip(),
                        "name": name.strip(),
                        "description": description.strip(),
                    },
                )
            except DORAPIError as exc:
                st.error(_human_error(exc, "oprette organisationen"))
            else:
                if isinstance(created, Mapping) and created.get("id"):
                    st.session_state["organization_id"] = str(created["id"])
                st.success("Organisationen er oprettet.")
                st.rerun()

    if active is None:
        st.info("Vælg en organisation i menuen for at redigere den.")
        return
    if active.get("is_admin") is not True:
        st.info("Du kan arbejde i organisationen, men kun en administrator kan ændre dens indstillinger.")
        return

    st.markdown("#### Aktiv organisation")
    st.caption(f"ID: `{active_id}`")
    with st.form(f"settings-edit-organization-{active_id}"):
        name = st.text_input("Navn", value=str(active.get("name") or ""))
        description = st.text_area(
            "Beskrivelse", value=str(active.get("description") or "")
        )
        submitted = st.form_submit_button("Gem organisation")
    if submitted:
        try:
            client.patch(
                f"/api/v1/control-plane/organizations/{active_id}",
                json={"name": name.strip(), "description": description.strip()},
            )
        except DORAPIError as exc:
            st.error(_human_error(exc, "gemme organisationen"))
        else:
            st.success("Organisationen er opdateret.")
            st.rerun()


def _render_user_settings(client: DORAPIClient) -> None:
    st.markdown("### Brugere")
    st.caption("Opret brugere, nulstil adgangskoder og styr administratoradgang uden terminal eller serverfiler.")
    organization_id = str(st.session_state.get("organization_id") or "").strip()
    if not organization_id:
        st.info("Vælg først en organisation.")
        return
    path = f"/api/v1/control-plane/organizations/{organization_id}/users"
    try:
        payload = client.get(path)
    except DORAPIError as exc:
        st.error(_human_error(exc, "hente brugerne"))
        return
    users = [dict(item) for item in payload if isinstance(item, Mapping)] if isinstance(payload, list) else []

    if users:
        rows = [
            {
                "Bruger": item.get("username"),
                "Navn": item.get("full_name") or "—",
                "E-mail": item.get("email") or "—",
                "Administrator": "Ja" if item.get("is_admin") else "Nej",
                "Status": "Deaktiveret" if item.get("disabled") else "Aktiv",
            }
            for item in users
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Der er ingen administrerbare brugere i organisationen endnu.")

    with st.expander("Opret bruger"):
        with st.form(f"settings-create-user-{organization_id}", clear_on_submit=True):
            username = st.text_input("Brugernavn")
            full_name = st.text_input("Navn")
            email = st.text_input("E-mail")
            password = st.text_input("Midlertidig adgangskode", type="password")
            is_admin = st.checkbox("Administrator")
            submitted = st.form_submit_button("Opret bruger", type="primary")
        if submitted:
            try:
                client.post(
                    path,
                    json={
                        "username": username.strip(),
                        "full_name": full_name.strip() or None,
                        "email": email.strip() or None,
                        "password": password,
                        "is_admin": is_admin,
                    },
                )
            except DORAPIError as exc:
                st.error(_human_error(exc, "oprette brugeren"))
            else:
                st.success("Brugeren er oprettet og kan logge ind.")
                st.rerun()

    if not users:
        return
    by_username = {str(item.get("username")): item for item in users if item.get("username")}
    selected = st.selectbox("Redigér bruger", list(by_username), key="settings-user-selector")
    user = by_username[selected]
    with st.form(f"settings-edit-user-{organization_id}-{selected}"):
        full_name = st.text_input("Navn", value=str(user.get("full_name") or ""))
        email = st.text_input("E-mail", value=str(user.get("email") or ""))
        is_admin = st.checkbox("Administrator", value=bool(user.get("is_admin")))
        disabled = st.checkbox("Deaktiver login", value=bool(user.get("disabled")))
        password = st.text_input(
            "Ny adgangskode",
            type="password",
            help="Lad feltet være tomt for at beholde den nuværende adgangskode.",
        )
        submitted = st.form_submit_button("Gem bruger")
    if submitted:
        body: dict[str, Any] = {
            "full_name": full_name.strip(),
            "email": email.strip(),
            "is_admin": is_admin,
            "disabled": disabled,
        }
        if password:
            body["password"] = password
        try:
            client.patch(f"{path}/{selected}", json=body)
        except DORAPIError as exc:
            st.error(_human_error(exc, "opdatere brugeren"))
        else:
            st.success("Brugeren er opdateret.")
            st.rerun()


def _render_system_settings(client: DORAPIClient) -> None:
    st.markdown("### System")
    st.caption("Systemstatus vises i menneskeligt sprog. Tekniske detaljer er sekundære.")
    try:
        ready = client.readiness()
    except DORAPIError:
        st.error("DORs systemtjenester svarer ikke som forventet lige nu.")
        return
    status = str(ready.get("status") or "unknown") if isinstance(ready, Mapping) else "unknown"
    if status == "ready":
        st.success("DOR er klar til arbejde, og databasen svarer.")
    else:
        st.warning("DOR er startet, men alle systemtjenester er ikke klar endnu.")

    with st.expander("Tekniske systemoplysninger"):
        if isinstance(ready, Mapping):
            st.json(dict(ready))
        st.caption(
            "Lager, workers og runtime-endpoints flyttes ind i denne sektion som server-ejede indstillinger; browseren skal ikke kende hemmelige filer eller miljøvariabler."
        )


def render_settings(client: DORAPIClient) -> None:
    """Render the single administration workspace for ordinary operation."""
    st.markdown(
        '<div class="eyebrow">DOR / INDSTILLINGER</div>'
        '<h1>Indstillinger</h1>'
        '<div class="subtitle">Opsæt organisation, brugere, integrationer og systemet uden terminal eller serverfiler.</div>',
        unsafe_allow_html=True,
    )
    tabs = st.tabs(["Organisation", "Brugere", "Integrationer", "System", "AI & Governance"])
    with tabs[0]:
        _render_organization_settings(client)
    with tabs[1]:
        _render_user_settings(client)
    with tabs[2]:
        render_redmine_integration(client)
    with tabs[3]:
        _render_system_settings(client)
    with tabs[4]:
        organization_id = str(st.session_state.get("organization_id") or "").strip()
        render_multi_bot_control_plane(client, organization_id)
