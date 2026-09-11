"""Administration capability rendered inside the canonical Operator GUI."""

from __future__ import annotations

from typing import Any, Literal, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.multi_bot_control_plane import render_multi_bot_control_plane
from dashboard.redmine_integration import render_redmine_integration

HealthState = Literal["healthy", "unhealthy", "unknown"]


def _human_error(exc: DORAPIError, action: str) -> str:
    if exc.status_code == 401:
        return "Din session er ikke længere gyldig. Log ind igen."
    if exc.status_code == 403:
        return f"Du har ikke administratorrettigheder til at {action}."
    if exc.status_code == 409:
        return f"DOR kunne ikke {action}, fordi oplysningerne konflikter med den aktuelle opsætning."
    if exc.status_code == 422:
        return "Kontrollér felterne. En eller flere værdier er ugyldige."
    if exc.status_code == 503:
        return f"DOR kan ikke {action} lige nu, fordi en nødvendig systemtjeneste ikke er klar."
    return f"DOR kunne ikke {action} lige nu (fejlkode {exc.status_code})."


def classify_health_status(payload: Any, *, expected: str) -> HealthState:
    """Classify only explicit backend health contracts."""
    if not isinstance(payload, Mapping):
        return "unknown"
    raw = payload.get("status")
    if not isinstance(raw, str) or not raw.strip():
        return "unknown"
    status = raw.strip().lower()
    if status == expected:
        return "healthy"
    if status in {"error", "unhealthy", "not_ready", "degraded"}:
        return "unhealthy"
    return "unknown"


def _organization_catalog(client: DORAPIClient) -> dict[str, Any] | None:
    payload = client.get("/api/v1/control-plane/organizations")
    if not isinstance(payload, Mapping):
        return None
    organizations = payload.get("organizations")
    if not isinstance(organizations, list):
        return None
    return dict(payload)


def _active_admin_organization(catalog: Mapping[str, Any], organization_id: str) -> dict[str, Any] | None:
    organizations = catalog.get("organizations")
    if not isinstance(organizations, list):
        return None
    for item in organizations:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("id") or "").strip() != organization_id:
            continue
        if item.get("is_admin") is not True:
            return None
        return dict(item)
    return None


def _render_organization_settings(client: DORAPIClient) -> None:
    st.markdown("### Organisationer")
    st.caption("Administrér organisationer gennem DORs backend. Det tekniske ID vælges én gang og forbliver stabilt.")
    active_id = str(st.session_state.get("organization_id") or "").strip()
    if not active_id:
        st.warning("Status kan ikke fastslås")
        return
    try:
        catalog = _organization_catalog(client)
    except DORAPIError as exc:
        st.error(_human_error(exc, "hente organisationerne"))
        return
    except Exception:
        st.error("Status kan ikke fastslås")
        return
    if catalog is None:
        st.error("Status kan ikke fastslås")
        return
    active = _active_admin_organization(catalog, active_id)
    if active is None:
        st.error("Administratoradgang til den aktive organisation kunne ikke bekræftes.")
        return
    organizations = [dict(item) for item in catalog["organizations"] if isinstance(item, Mapping) and item.get("id")]
    st.dataframe(
        [{"Organisation": item.get("name") or item.get("id"), "ID": item.get("id"), "Administrator": item.get("is_admin") is True} for item in organizations],
        hide_index=True,
        use_container_width=True,
    )
    with st.expander("Opret ny organisation", expanded=False):
        with st.form("settings-create-organization", clear_on_submit=True):
            organization_id = st.text_input("Organisationens ID", placeholder="min-organisation", help="Stabilt ID til DOR. Kan ikke omdøbes efter oprettelse.")
            name = st.text_input("Navn")
            description = st.text_area("Beskrivelse")
            submitted = st.form_submit_button("Opret organisation", type="primary")
        if submitted:
            try:
                created = client.post("/api/v1/control-plane/organizations", json={"id": organization_id.strip(), "name": name.strip(), "description": description.strip()})
            except DORAPIError as exc:
                st.error(_human_error(exc, "oprette organisationen"))
            else:
                if not isinstance(created, Mapping) or not created.get("id"):
                    st.error("Status kan ikke fastslås")
                    return
                st.session_state["organization_id"] = str(created["id"])
                st.success("Organisationen er oprettet af backenden.")
                st.rerun()
    st.markdown("#### Aktiv organisation")
    st.caption(f"ID: `{active_id}`")
    with st.form(f"settings-edit-organization-{active_id}"):
        name = st.text_input("Navn", value=str(active.get("name") or ""))
        description = st.text_area("Beskrivelse", value=str(active.get("description") or ""))
        submitted = st.form_submit_button("Gem organisation")
    if submitted:
        try:
            updated = client.patch(f"/api/v1/control-plane/organizations/{active_id}", json={"name": name.strip(), "description": description.strip()})
        except DORAPIError as exc:
            st.error(_human_error(exc, "gemme organisationen"))
        else:
            if not isinstance(updated, Mapping) or updated.get("id") != active_id:
                st.error("Status kan ikke fastslås")
                return
            st.success("Organisationen er opdateret af backenden.")
            st.rerun()


def _render_user_settings(client: DORAPIClient) -> None:
    st.markdown("### Brugere")
    st.caption("Opret brugere, nulstil adgangskoder og administrér den eksisterende organization-admin markering.")
    organization_id = str(st.session_state.get("organization_id") or "").strip()
    if not organization_id:
        st.warning("Status kan ikke fastslås")
        return
    path = f"/api/v1/control-plane/organizations/{organization_id}/users"
    try:
        payload = client.get(path)
    except DORAPIError as exc:
        st.error(_human_error(exc, "hente brugerne"))
        return
    except Exception:
        st.error("Status kan ikke fastslås")
        return
    if not isinstance(payload, list):
        st.error("Status kan ikke fastslås")
        return
    users = [dict(item) for item in payload if isinstance(item, Mapping)]
    if users:
        st.dataframe(
            [{"Bruger": item.get("username"), "Navn": item.get("full_name") or "—", "E-mail": item.get("email") or "—", "Administrator": "Ja" if item.get("is_admin") else "Nej", "Status": "Deaktiveret" if item.get("disabled") else "Aktiv"} for item in users],
            use_container_width=True,
            hide_index=True,
        )
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
                created = client.post(path, json={"username": username.strip(), "full_name": full_name.strip() or None, "email": email.strip() or None, "password": password, "is_admin": is_admin})
            except DORAPIError as exc:
                st.error(_human_error(exc, "oprette brugeren"))
            else:
                if not isinstance(created, Mapping) or not created.get("username"):
                    st.error("Status kan ikke fastslås")
                    return
                st.success("Brugeren er oprettet af backenden.")
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
        password = st.text_input("Ny adgangskode", type="password", help="Lad feltet være tomt for at beholde den nuværende adgangskode.")
        submitted = st.form_submit_button("Gem bruger")
    if submitted:
        body: dict[str, Any] = {"full_name": full_name.strip(), "email": email.strip(), "is_admin": is_admin, "disabled": disabled}
        if password:
            body["password"] = password
        try:
            updated = client.patch(f"{path}/{selected}", json=body)
        except DORAPIError as exc:
            st.error(_human_error(exc, "opdatere brugeren"))
        else:
            if not isinstance(updated, Mapping) or updated.get("username") != selected:
                st.error("Status kan ikke fastslås")
                return
            st.success("Brugeren er opdateret af backenden.")
            st.rerun()


def _render_project_settings(client: DORAPIClient) -> None:
    st.markdown("### Projekter")
    st.caption("Read-only administrativt katalog. Project lifecycle, Cases og execution forbliver i Operator/Case Journey.")
    organization_id = str(st.session_state.get("organization_id") or "").strip()
    if not organization_id:
        st.warning("Status kan ikke fastslås")
        return
    try:
        payload = client.get("/api/v1/control-plane/projects", params={"organization_id": organization_id})
    except DORAPIError as exc:
        st.error(_human_error(exc, "hente projekterne"))
        return
    except Exception:
        st.error("Status kan ikke fastslås")
        return
    if not isinstance(payload, Mapping) or not isinstance(payload.get("projects"), list):
        st.error("Status kan ikke fastslås")
        return
    payload_org = str(payload.get("organization_id") or "").strip()
    if payload_org and payload_org != organization_id:
        st.error("Status kan ikke fastslås")
        return
    projects = [dict(item) for item in payload["projects"] if isinstance(item, Mapping) and (not item.get("organization_id") or str(item.get("organization_id")) == organization_id)]
    if not projects:
        st.info("Ingen projekter i den aktive organisation.")
    else:
        st.dataframe(
            [{"Projekt": item.get("name") or item.get("project_id"), "ID": item.get("project_id"), "Status": item.get("status") or "Ukendt", "Revision": item.get("revision") or "—", "Opdateret": item.get("updated_at") or "—"} for item in projects],
            hide_index=True,
            use_container_width=True,
        )
    st.info("Project membership, departments og repository mappings tilføjes ikke her, før der findes canonical backend-kontrakter.")


def _show_ai_test_result(payload: Any) -> None:
    if not isinstance(payload, Mapping):
        st.error("Status kan ikke fastslås")
        return
    result = dict(payload)
    if result.get("model_available") is True:
        st.success("Forbindelsen virker, API-nøglen accepteres, og modellen er tilgængelig.")
        return
    error = str(result.get("error") or "")
    if error == "not_configured":
        st.warning("AI-forbindelsen er ikke konfigureret færdigt endnu.")
    elif error == "authentication_failed":
        st.error("AI-endpointet afviste API-nøglen. Kontrollér nøglen og prøv igen.")
    elif error == "model_not_found":
        st.error("Forbindelsen virker, men den valgte model blev ikke fundet på endpointet.")
    elif error == "models_endpoint_not_supported":
        st.error("Endpointet svarer, men understøtter ikke den OpenAI-kompatible modeloversigt.")
    elif error == "connection_error":
        st.error("DOR kunne ikke nå AI-endpointet. Kontrollér adresse og netværk.")
    else:
        st.error("Status kan ikke fastslås")


def _render_ai_settings(client: DORAPIClient) -> None:
    organization_id = str(st.session_state.get("organization_id") or "").strip()
    st.markdown("### Implementation AI")
    st.caption("Model, endpoint og credential administreres via backenden. API-nøglen gemmes krypteret og vises aldrig igen.")
    if not organization_id:
        st.warning("Status kan ikke fastslås")
        return
    try:
        payload = client.get("/api/v1/integrations/ai/config", params={"organization_id": organization_id})
    except DORAPIError as exc:
        st.error(_human_error(exc, "hente AI-indstillingerne"))
        return
    except Exception:
        st.error("Status kan ikke fastslås")
        return
    if not isinstance(payload, Mapping):
        st.error("Status kan ikke fastslås")
        return
    config = dict(payload)
    if str(config.get("organization_id") or "").strip() != organization_id or not isinstance(config.get("api_key_configured"), bool):
        st.error("Status kan ikke fastslås")
        return
    if config.get("active_for_new_tasks") is True:
        st.success("AI-konfigurationen er aktiv for nye implementeringsopgaver.")
    else:
        st.warning("DOR mangler en komplet AI-konfiguration til nye implementeringsopgaver.")
    if config.get("source") == "environment":
        st.info("DOR bruger stadig den ældre serverkonfiguration. Gem formularen for at flytte indstillingerne ind i DOR.")
    with st.form(f"implementation-ai-settings-{organization_id}"):
        model = st.text_input("Model", value=str(config.get("model") or ""))
        base_url = st.text_input("API-base-URL", value=str(config.get("base_url") or ""))
        key_label = "Ny API-nøgle (lad feltet være tomt for at beholde den gemte)" if config.get("api_key_configured") else "API-nøgle"
        api_key = st.text_input(key_label, type="password")
        saved = st.form_submit_button("Gem AI-indstillinger", type="primary")
    if saved:
        body: dict[str, Any] = {"organization_id": organization_id, "model": model.strip(), "base_url": base_url.strip()}
        if api_key.strip():
            body["api_key"] = api_key.strip()
        try:
            saved_config = client.put("/api/v1/integrations/ai/config", json=body)
        except DORAPIError as exc:
            st.error(_human_error(exc, "gemme AI-indstillingerne"))
        else:
            if not isinstance(saved_config, Mapping):
                st.error("Status kan ikke fastslås")
                return
            st.success("AI-indstillingerne er gemt af backenden.")
            st.rerun()
    if st.button("Test AI-forbindelse", key=f"test-implementation-ai-{organization_id}", use_container_width=True):
        try:
            result = client.post("/api/v1/integrations/ai/test", params={"organization_id": organization_id})
        except DORAPIError as exc:
            st.error(_human_error(exc, "teste AI-forbindelsen"))
        else:
            _show_ai_test_result(result)


def _render_health_card(title: str, payload: Any, *, expected: str, healthy_text: str, unhealthy_text: str) -> None:
    state = classify_health_status(payload, expected=expected)
    with st.container(border=True):
        st.subheader(title)
        if state == "healthy":
            st.success(healthy_text)
        elif state == "unhealthy":
            st.error(unhealthy_text)
        else:
            st.warning("Status kan ikke fastslås")


def _render_system_settings(client: DORAPIClient) -> None:
    st.markdown("### System configuration / health")
    st.caption("Liveness og readiness vises fra canonical backend health contracts. Ukendte responses bliver aldrig omskrevet til Healthy.")
    try:
        health = client.health()
    except Exception:
        health = None
    try:
        ready = client.readiness()
    except Exception:
        ready = None
    cols = st.columns(2)
    with cols[0]:
        _render_health_card("API liveness", health, expected="ok", healthy_text="API svarer som forventet.", unhealthy_text="API rapporterer en usund tilstand.")
    with cols[1]:
        _render_health_card("Database / readiness", ready, expected="ready", healthy_text="DOR er klar til arbejde, og databasen svarer.", unhealthy_text="DORs nødvendige systemtjenester er ikke klar.")
    if isinstance(ready, Mapping) and ready.get("migration_head"):
        st.caption(f"Migration head: `{ready['migration_head']}`")
    with st.expander("Tekniske systemoplysninger"):
        if isinstance(health, Mapping):
            st.json({"health": dict(health)})
        if isinstance(ready, Mapping):
            st.json({"readiness": dict(ready)})
        st.caption("MFA/SSO, sessions og generisk security policy er read-only/unsupported, indtil der findes en sikker mutable backend-kontrakt.")


def render_settings(client: DORAPIClient) -> None:
    """Render backend-authorized administration inside GUI-01."""
    st.markdown(
        '<div class="eyebrow">DOR / ADMINISTRATION</div>'
        '<h1>Administration</h1>'
        '<div class="subtitle">Organisation, brugere, projekter, integrationer og systemstatus i den samme Operator GUI.</div>',
        unsafe_allow_html=True,
    )
    tabs = st.tabs(["Organisationer", "Brugere", "Projekter", "Redmine", "System", "AI & Governance"])
    with tabs[0]:
        _render_organization_settings(client)
    with tabs[1]:
        _render_user_settings(client)
    with tabs[2]:
        _render_project_settings(client)
    with tabs[3]:
        render_redmine_integration(client)
    with tabs[4]:
        _render_system_settings(client)
    with tabs[5]:
        organization_id = str(st.session_state.get("organization_id") or "").strip()
        render_multi_bot_control_plane(client, organization_id)
