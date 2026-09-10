"""GUI-03 — standalone DOR Administration & Configuration Platform.

This Streamlit app is intentionally a thin administrative client.  It never
executes workflows, applies patches, creates pull requests or fabricates local
authority.  Mutations are sent to the canonical FastAPI contracts and success
is shown only after the backend returns success.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

import streamlit as st

from dashboard.admin_api import AdminAPI, CAPABILITIES
from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.state import authenticated, clear_auth, init_state


st.set_page_config(page_title="DOR Administration", page_icon="⚙️", layout="wide")
init_state()


STATUS_LABELS = {
    "implemented": "Understøttet",
    "read-only": "Read-only",
    "limited": "Begrænset",
    "unsupported": "Ikke understøttet af backend",
}


def _client() -> AdminAPI:
    return AdminAPI(DORAPIClient(token=st.session_state.get("access_token")))


def _format_time(value: Any) -> str:
    if not value:
        return "—"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).replace("T", " ").replace("+00:00", " UTC")


def _error(exc: Exception, *, action: str = "Handlingen") -> None:
    if isinstance(exc, DORAPIError):
        if exc.status_code == 401:
            clear_auth()
            st.error("Sessionen er udløbet. Log ind igen.")
            st.rerun()
        if exc.status_code == 403:
            st.error(f"{action} blev afvist af backend: du har ikke den nødvendige adgang.")
            return
        if exc.status_code == 404:
            st.error(f"{action} kunne ikke gennemføres: ressourcen findes ikke længere.")
            return
        if exc.status_code == 409:
            st.error(f"{action} kunne ikke gennemføres på grund af konflikt eller ændret state.")
            st.caption(str(exc))
            return
        if exc.status_code == 422:
            st.error(f"{action} blev afvist af backend-valideringen.")
            st.caption(str(exc))
            return
        if exc.status_code == 503:
            st.error(f"{action} er midlertidigt utilgængelig i backend.")
            st.caption(str(exc))
            return
        st.error(f"{action} fejlede ({exc.status_code}).")
        st.caption(str(exc))
        return
    st.error(f"{action} fejlede. Status kan ikke fastslås.")
    st.caption(str(exc))


def _safe(call: Callable[[], Any]) -> tuple[Any | None, Exception | None]:
    try:
        return call(), None
    except Exception as exc:  # surface transport/backend state explicitly
        return None, exc


def _login() -> None:
    st.title("⚙️ DOR Administration")
    st.caption("Administration og konfiguration via DORs authoritative backend")
    with st.form("admin_login"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        submitted = st.form_submit_button("Log ind", type="primary")
    if submitted:
        try:
            client = DORAPIClient()
            token = client.login(username, password)
            st.session_state["access_token"] = token
            st.session_state["username"] = username
            st.rerun()
        except Exception as exc:
            _error(exc, action="Login")


def _organization_catalog(admin: AdminAPI) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    payload, exc = _safe(admin.organizations)
    if exc:
        _error(exc, action="Organisationer")
        return [], None
    organizations = list((payload or {}).get("organizations") or [])
    admin_orgs = [item for item in organizations if item.get("is_admin") is True]
    if not admin_orgs:
        st.error("Ingen organisation med administrativ adgang er tilgængelig for denne bruger.")
        st.caption("GUI-03 giver ikke lokal adgang, når backend ikke har bekræftet admin-medlemskab.")
        return organizations, None

    by_id = {str(item.get("id")): item for item in admin_orgs}
    current = st.session_state.get("admin_organization_id")
    preferred = (payload or {}).get("active_organization_id")
    if current not in by_id:
        current = preferred if preferred in by_id else next(iter(by_id))
        st.session_state["admin_organization_id"] = current

    labels = {
        org_id: f"{by_id[org_id].get('name') or org_id} · {org_id}" for org_id in by_id
    }
    selected = st.sidebar.selectbox(
        "Administrativ organisation",
        options=list(by_id),
        index=list(by_id).index(current),
        format_func=lambda value: labels[value],
        key="admin_organization_selector",
    )
    st.session_state["admin_organization_id"] = selected
    return organizations, by_id[selected]


def _sidebar(selected_org: dict[str, Any] | None) -> str:
    st.sidebar.title("DOR Administration")
    if selected_org:
        st.sidebar.caption(f"Scope: {selected_org.get('name') or selected_org.get('id')}")
    page = st.sidebar.radio(
        "Navigation",
        ["Overblik", "Organisation", "Brugere", "Projekter", "Integrationer", "System & Security"],
    )
    st.sidebar.divider()
    st.sidebar.caption(f"Bruger: {st.session_state.get('username') or '—'}")
    if st.sidebar.button("Log ud"):
        clear_auth()
        st.session_state.pop("admin_organization_id", None)
        st.session_state.pop("admin_organization_selector", None)
        st.rerun()
    return page


def _status_card(title: str, value: str, detail: str = "") -> None:
    with st.container(border=True):
        st.subheader(title)
        st.write(value)
        if detail:
            st.caption(detail)


def _render_overview(admin: AdminAPI, org: dict[str, Any]) -> None:
    st.header("Administration · Overblik")
    st.write("Er DOR korrekt konfigureret, og er der noget administratoren skal gøre?")

    health, health_exc = _safe(admin.health)
    ready, ready_exc = _safe(admin.readiness)
    redmine, redmine_exc = _safe(lambda: admin.test_redmine(str(org["id"])))

    cols = st.columns(3)
    with cols[0]:
        if health_exc:
            _status_card("API", "Status kan ikke fastslås")
        else:
            _status_card("API", "OK" if health.get("status") == "ok" else "Warning", str(health))
    with cols[1]:
        if ready_exc:
            _status_card("Database / readiness", "Status kan ikke fastslås")
        else:
            status = "OK" if ready.get("status") == "ready" else "Warning"
            _status_card("Database / readiness", status, f"Migration: {ready.get('migration_head') or 'ukendt'}")
    with cols[2]:
        if redmine_exc:
            _status_card("Redmine", "Status kan ikke fastslås")
        else:
            if redmine.get("verified") is True:
                label = "Connected"
            elif redmine.get("configured") is False:
                label = "Ikke konfigureret"
            elif redmine.get("reachable") is False:
                label = "Connection failed"
            else:
                label = "Warning"
            _status_card("Redmine", label, str(redmine.get("error") or ""))

    st.subheader("Backend capability map")
    rows = [
        {
            "Capability": item.label,
            "Status": STATUS_LABELS[item.support],
            "Kontrakt": item.detail,
        }
        for item in CAPABILITIES
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    st.info(
        "Capabilities markeret som ikke understøttet får ikke lokale admin-formularer. "
        "Det forhindrer GUI-03 i at blive en konkurrerende source of truth."
    )


def _render_organization(admin: AdminAPI, org: dict[str, Any]) -> None:
    st.header("Organisation")
    st.caption("Organisationens ID er immutable; navn og beskrivelse administreres via backend.")
    with st.form("organization_edit"):
        st.text_input("Organisation ID", value=str(org.get("id") or ""), disabled=True)
        name = st.text_input("Navn", value=str(org.get("name") or ""))
        description = st.text_area("Beskrivelse", value=str(org.get("description") or ""))
        save = st.form_submit_button("Gem organisation", type="primary")
    if save:
        try:
            updated = admin.update_organization(str(org["id"]), name=name, description=description)
            st.success("Organisationen blev gemt af backend.")
            st.caption(f"Opdateret: {_format_time(updated.get('updated_at'))}")
        except Exception as exc:
            _error(exc, action="Opdatering af organisation")

    st.divider()
    st.subheader("Opret organisation")
    st.caption("Kræver et eksisterende admin-medlemskab; den aktuelle admin tilknyttes den nye organisation.")
    with st.form("organization_create", clear_on_submit=False):
        organization_id = st.text_input("Nyt organisation-ID")
        new_name = st.text_input("Nyt organisationsnavn")
        new_description = st.text_area("Ny beskrivelse")
        confirmed = st.checkbox("Jeg bekræfter oprettelsen af denne tenant/organisation")
        create = st.form_submit_button("Opret organisation")
    if create:
        if not confirmed:
            st.warning("Bekræft oprettelsen først.")
        else:
            try:
                created = admin.create_organization(
                    organization_id=organization_id,
                    name=new_name,
                    description=new_description,
                )
                st.success(f"Organisation `{created.get('id')}` blev oprettet af backend.")
            except Exception as exc:
                _error(exc, action="Oprettelse af organisation")


def _render_users(admin: AdminAPI, org: dict[str, Any]) -> None:
    organization_id = str(org["id"])
    st.header("Brugere & adgang")
    users, exc = _safe(lambda: admin.users(organization_id))
    if exc:
        _error(exc, action="Brugeroversigt")
        return
    users = users or []
    st.dataframe(
        [
            {
                "Brugernavn": item.get("username"),
                "Navn": item.get("full_name") or "—",
                "E-mail": item.get("email") or "—",
                "Status": "Deaktiveret" if item.get("disabled") else "Aktiv",
                "Organisation admin": bool(item.get("is_admin")),
            }
            for item in users
        ],
        hide_index=True,
        use_container_width=True,
    )

    with st.expander("Opret bruger", expanded=not users):
        st.caption("Backend understøtter direkte brugeroprettelse, ikke invitationer. Password vises aldrig igen.")
        with st.form("admin_create_user"):
            username = st.text_input("Brugernavn")
            full_name = st.text_input("Navn")
            email = st.text_input("E-mail")
            password = st.text_input("Midlertidig adgangskode", type="password")
            is_admin = st.checkbox("Organisation admin")
            confirm = st.checkbox("Jeg bekræfter brugeroprettelsen og den valgte adgang")
            submitted = st.form_submit_button("Opret bruger")
        if submitted:
            if not confirm:
                st.warning("Bekræft brugeroprettelsen først.")
            else:
                try:
                    admin.create_user(
                        organization_id,
                        username=username,
                        password=password,
                        email=email or None,
                        full_name=full_name or None,
                        is_admin=is_admin,
                    )
                    st.success("Brugeren blev oprettet af backend.")
                    st.rerun()
                except Exception as user_exc:
                    _error(user_exc, action="Brugeroprettelse")

    if not users:
        return
    st.subheader("Rediger bruger")
    by_username = {str(item["username"]): item for item in users}
    selected_username = st.selectbox("Bruger", list(by_username))
    selected = by_username[selected_username]
    with st.form("admin_edit_user"):
        full_name = st.text_input("Navn", value=str(selected.get("full_name") or ""))
        email = st.text_input("E-mail", value=str(selected.get("email") or ""))
        disabled = st.checkbox("Deaktiveret", value=bool(selected.get("disabled")))
        is_admin = st.checkbox("Organisation admin", value=bool(selected.get("is_admin")))
        new_password = st.text_input("Ny adgangskode (tom = uændret)", type="password")
        sensitive_change = disabled != bool(selected.get("disabled")) or is_admin != bool(selected.get("is_admin")) or bool(new_password)
        confirm = st.checkbox("Jeg bekræfter den sikkerhedsrelevante ændring", disabled=not sensitive_change)
        update = st.form_submit_button("Gem bruger")
    if update:
        if sensitive_change and not confirm:
            st.warning("Bekræft den sikkerhedsrelevante ændring først.")
            return
        try:
            admin.update_user(
                organization_id,
                selected_username,
                full_name=full_name,
                email=email,
                password=new_password or None,
                disabled=disabled,
                is_admin=is_admin,
            )
            st.success("Brugeren blev opdateret af backend.")
            st.rerun()
        except Exception as user_exc:
            _error(user_exc, action="Brugeropdatering")


def _render_projects(admin: AdminAPI, org: dict[str, Any]) -> None:
    st.header("Projekter")
    st.caption("Administrativ projektoversigt. Lifecycle, Cases og execution forbliver i GUI-01.")
    payload, exc = _safe(lambda: admin.projects(str(org["id"])))
    if exc:
        _error(exc, action="Projektoversigt")
        return
    projects = list((payload or {}).get("projects") or [])
    if not projects:
        st.info("Ingen projekter i den valgte organisation.")
        return
    st.dataframe(
        [
            {
                "Projekt": p.get("name") or p.get("project_id"),
                "ID": p.get("project_id"),
                "Status": p.get("status") or "Ukendt",
                "Revision": p.get("revision"),
                "Opdateret": _format_time(p.get("updated_at")),
            }
            for p in projects
        ],
        hide_index=True,
        use_container_width=True,
    )
    st.info("Backend eksponerer ikke et separat administrativt project-membership/repository-mapping contract. Ingen lokal mapping-state oprettes her.")


def _connection_result(result: dict[str, Any] | None) -> None:
    if result is None:
        st.warning("Status kan ikke fastslås")
        return
    if result.get("verified") is True or result.get("ok") is True:
        st.success("Forbindelsen er verificeret af backend.")
    elif result.get("configured") is False:
        st.warning("Integrationen er ikke fuldt konfigureret.")
    else:
        st.error("Forbindelsen kunne ikke verificeres.")
    safe = {key: value for key, value in result.items() if "key" not in key.lower() and "secret" not in key.lower() and "token" not in key.lower()}
    st.json(safe)


def _render_integrations(admin: AdminAPI, org: dict[str, Any]) -> None:
    organization_id = str(org["id"])
    st.header("Integrationer")
    st.caption("Integrationer konfigurerer eksterne forbindelser; de bliver ikke alternative DOR state machines.")
    redmine_tab, ai_tab = st.tabs(["Redmine", "Implementation AI"])

    with redmine_tab:
        config, exc = _safe(lambda: admin.redmine_config(organization_id))
        if exc:
            _error(exc, action="Redmine-konfiguration")
        elif config is not None:
            with st.form("redmine_config"):
                url = st.text_input("Redmine URL", value=str(config.get("url") or ""))
                project_id = st.text_input("Redmine project ID", value=str(config.get("project_id") or ""))
                st.text_input(
                    "Eksisterende credential",
                    value="Konfigureret" if config.get("api_key_configured") else "Ikke konfigureret",
                    disabled=True,
                )
                api_key = st.text_input("Erstat API token (tom = behold eksisterende)", type="password")
                save = st.form_submit_button("Gem Redmine-konfiguration", type="primary")
            if save:
                try:
                    saved = admin.save_redmine(organization_id, url=url, project_id=project_id, api_key=api_key or None)
                    st.success("Redmine-konfigurationen blev gemt af backend.")
                    st.caption(f"Kilde: {saved.get('source')} · Opdateret: {_format_time(saved.get('updated_at'))}")
                    st.rerun()
                except Exception as save_exc:
                    _error(save_exc, action="Redmine-konfiguration")
            if st.button("Test forbindelse", key="test_redmine"):
                result, test_exc = _safe(lambda: admin.test_redmine(organization_id))
                if test_exc:
                    _error(test_exc, action="Redmine forbindelsestest")
                else:
                    _connection_result(result)

    with ai_tab:
        config, exc = _safe(lambda: admin.ai_config(organization_id))
        if exc:
            _error(exc, action="Implementation AI-konfiguration")
        elif config is not None:
            with st.form("ai_config"):
                model = st.text_input("Model", value=str(config.get("model") or ""))
                base_url = st.text_input("Provider base URL", value=str(config.get("base_url") or ""))
                st.text_input(
                    "Eksisterende credential",
                    value="Konfigureret" if config.get("api_key_configured") else "Ikke konfigureret",
                    disabled=True,
                )
                api_key = st.text_input("Erstat API key (tom = behold eksisterende)", type="password")
                save = st.form_submit_button("Gem AI-konfiguration", type="primary")
            if save:
                try:
                    saved = admin.save_ai(organization_id, model=model, base_url=base_url, api_key=api_key or None)
                    st.success("Implementation AI-konfigurationen blev gemt af backend.")
                    st.caption(f"Aktiv for nye tasks: {saved.get('active_for_new_tasks')} · Opdateret: {_format_time(saved.get('updated_at'))}")
                    st.rerun()
                except Exception as save_exc:
                    _error(save_exc, action="Implementation AI-konfiguration")
            if st.button("Test AI-forbindelse", key="test_ai"):
                result, test_exc = _safe(lambda: admin.test_ai(organization_id))
                if test_exc:
                    _error(test_exc, action="AI forbindelsestest")
                else:
                    _connection_result(result)

    st.subheader("Andre providers")
    st.info("GitHub/GitLab repository mappings vises ikke som konfigurerbare, fordi repositoryet ikke eksponerer en authoritative GUI-03 mapping-kontrakt.")


def _render_system(admin: AdminAPI) -> None:
    st.header("System & Security")
    health, health_exc = _safe(admin.health)
    ready, ready_exc = _safe(admin.readiness)
    cols = st.columns(2)
    with cols[0]:
        st.subheader("Liveness")
        if health_exc:
            st.warning("Status kan ikke fastslås")
        else:
            st.json(health)
    with cols[1]:
        st.subheader("Readiness")
        if ready_exc:
            st.warning("Status kan ikke fastslås")
        else:
            st.json(ready)

    st.subheader("Security administration")
    st.write("Authentication, tenant scope og authorization håndhæves af backend. GUI-03 har ingen lokal authority.")
    st.warning("Environment, MFA/SSO, sessions, API-key lifecycle og generisk security policy har ingen sikker mutable admin-kontrakt i den nuværende API og kan derfor ikke ændres her.")
    st.subheader("Audit")
    st.error("Authoritative administrativ audit-query er ikke eksponeret af backend. GUI-03 fabrikerer derfor ikke audit records.")
    st.caption("Projekt-events er ikke genbrugt som falsk global admin-audit, fordi organisation-, bruger- og integrationsmutationer ikke dokumenteres af den kontrakt.")


def main() -> None:
    if not authenticated():
        _login()
        return

    admin = _client()
    _, selected_org = _organization_catalog(admin)
    page = _sidebar(selected_org)
    if selected_org is None:
        st.stop()

    if page == "Overblik":
        _render_overview(admin, selected_org)
    elif page == "Organisation":
        _render_organization(admin, selected_org)
    elif page == "Brugere":
        _render_users(admin, selected_org)
    elif page == "Projekter":
        _render_projects(admin, selected_org)
    elif page == "Integrationer":
        _render_integrations(admin, selected_org)
    elif page == "System & Security":
        _render_system(admin)


main()
