"""DOR Customer Portal — independent Streamlit presentation on port 8502."""
from __future__ import annotations

from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIError
from customer_gui.client import CustomerAPI, CustomerContractError
from customer_gui.view_model import (
    CANONICAL_JOURNEY,
    UNKNOWN_STATUS,
    JourneyState,
    completion_evidence,
    customer_execution_status,
    decision_actions,
    journey,
    resolve_provenance,
)

st.set_page_config(
    page_title="DOR Kundeportal",
    page_icon="D",
    layout="wide",
    initial_sidebar_state="expanded",
)

NAV = ("Dashboard", "Projekter", "Beslutninger", "Historik")


def _css() -> None:
    st.markdown(
        """
        <style>
        :root { --ink:#17353d; --muted:#6c8186; --paper:#f7f6f1; --card:#fffefa; --line:#dfe6e1; --accent:#2f8273; }
        .stApp { background:var(--paper); color:var(--ink); }
        [data-testid="stSidebar"] { background:#143943; }
        [data-testid="stSidebar"] * { color:#edf5f1 !important; }
        .block-container { max-width:1120px; padding-top:2.7rem; padding-bottom:5rem; }
        .eyebrow { color:var(--muted); font-size:.68rem; font-weight:800; letter-spacing:.14em; text-transform:uppercase; }
        .subtitle { color:var(--muted); max-width:760px; margin-bottom:1.5rem; }
        div[data-testid="stVerticalBlockBorderWrapper"] { background:var(--card); border-color:var(--line)!important; border-radius:18px!important; }
        .journey { display:grid; grid-template-columns:repeat(6,1fr); gap:.45rem; margin:.8rem 0 1.4rem; }
        .journey-step { padding:.8rem .55rem; border:1px solid var(--line); border-radius:12px; text-align:center; font-size:.76rem; font-weight:700; background:#fff; }
        .journey-step.current { border:2px solid var(--accent); }
        .journey-step.completed { background:#edf5f1; }
        .journey-step.blocked, .journey-step.failed { background:#fff1ed; }
        .journey-step.unknown { background:#f1f0ec; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _clear_auth() -> None:
    for key in (
        "customer_access_token",
        "customer_username",
        "customer_nav",
        "customer_project_id",
    ):
        st.session_state.pop(key, None)


def _api() -> CustomerAPI:
    return CustomerAPI(token=st.session_state.get("customer_access_token"))


def _login() -> None:
    st.markdown('<div class="eyebrow">DOR CUSTOMER PORTAL</div>', unsafe_allow_html=True)
    st.title("Dit projekt i DOR")
    st.markdown(
        '<div class="subtitle">Se hvad der sker, hvorfor det sker, og hvornår DOR har brug for din beslutning.</div>',
        unsafe_allow_html=True,
    )
    with st.form("customer-login"):
        username = st.text_input("Brugernavn")
        password = st.text_input("Adgangskode", type="password")
        submitted = st.form_submit_button("Log ind", type="primary")
    if submitted:
        try:
            token = CustomerAPI().login(username, password)
        except DORAPIError as exc:
            if exc.status_code == 401:
                st.error("Brugernavn eller adgangskode blev ikke godkendt.")
            else:
                st.error("DOR kunne ikke gennemføre login lige nu.")
        else:
            st.session_state["customer_access_token"] = token
            st.session_state["customer_username"] = username
            st.rerun()


def _sidebar() -> str:
    current = st.session_state.get("customer_nav")
    if current not in NAV:
        st.session_state["customer_nav"] = NAV[0]
    with st.sidebar:
        st.markdown("### DOR Kundeportal")
        nav = st.radio("Navigation", NAV, key="customer_nav", label_visibility="collapsed")
        st.divider()
        st.caption(st.session_state.get("customer_username") or "—")
        if st.button("Log ud", use_container_width=True):
            _clear_auth()
            st.rerun()
    return nav


def _load_projects(api: CustomerAPI) -> tuple[dict[str, Any], list[dict[str, Any]]] | None:
    try:
        organization = api.active_organization()
        organization_id = str(organization.get("id") or "").strip()
        if not organization_id:
            raise CustomerContractError("active organization identity is missing")
        return organization, api.projects(organization_id)
    except DORAPIError as exc:
        if exc.status_code == 401:
            _clear_auth()
            st.error("Din session er udløbet. Log ind igen.")
        elif exc.status_code in {403, 404}:
            st.error("Du har ikke adgang til den ønskede projektinformation.")
        else:
            st.error("DORs backend er ikke tilgængelig lige nu.")
    except CustomerContractError:
        st.error(UNKNOWN_STATUS)
    return None


def _project_runtime(api: CustomerAPI, project: Mapping[str, Any]) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    execution = api.project_execution(project)
    if execution is None:
        return None, [], []
    workflow_id = str(execution.get("workflow_id") or "")
    return execution, api.gates(workflow_id), api.proposals(workflow_id)


def _render_journey(project: Mapping[str, Any], execution: Mapping[str, Any] | None, gates: list[dict[str, Any]], proposals: list[dict[str, Any]]) -> None:
    steps = journey(project, execution, gates, proposals)
    assert tuple(step.label for step in steps) == CANONICAL_JOURNEY
    markup = '<div class="journey">' + "".join(
        f'<div class="journey-step {step.state.value}">{step.label}</div>' for step in steps
    ) + "</div>"
    st.markdown(markup, unsafe_allow_html=True)


def _render_provenance(project: Mapping[str, Any], execution: Mapping[str, Any] | None, proposal: Mapping[str, Any] | None = None) -> None:
    provenance = resolve_provenance(project, execution, proposal)
    with st.expander("Vis detaljer"):
        if provenance is None:
            st.write(f"Execution provenance: **{UNKNOWN_STATUS}**")
            return
        st.write(f"Case ID: `{provenance.case_id}`")
        st.write(f"Plan fingerprint: `{provenance.plan_request_fingerprint}`")
        st.write(f"Workflow ID: `{provenance.workflow_id}`")
        if provenance.proposal_id:
            st.write(f"Proposal ID: `{provenance.proposal_id}`")
        else:
            st.caption("Ingen Proposal er knyttet til denne visning.")
        st.caption("Backend eksponerer ikke et separat Plan ID i den aktive project-scope kontrakt.")


def _render_project(api: CustomerAPI, project: dict[str, Any]) -> None:
    st.markdown(f"## {project.get('name') or 'Projekt'}")
    if project.get("description"):
        st.write(project["description"])
    intent = project.get("intent") if isinstance(project.get("intent"), Mapping) else {}
    if intent and intent.get("goal"):
        st.caption(f"Mål: {intent['goal']}")

    try:
        execution, gates, proposals = _project_runtime(api, project)
    except (DORAPIError, CustomerContractError):
        st.error(UNKNOWN_STATUS)
        execution, gates, proposals = None, [], []

    _render_journey(project, execution, gates, proposals)
    status = customer_execution_status(execution) if execution is not None else None
    cols = st.columns(3)
    cols[0].metric("Projektstatus", str(project.get("status") or UNKNOWN_STATUS))
    cols[1].metric("Aktuelt arbejde", status.label if status else "Ikke startet")
    cols[2].metric("Beslutninger", sum(1 for gate in gates if decision_actions(gate)))

    st.markdown("### Aktuelt arbejdsgrundlag")
    fingerprint = str(project.get("active_plan_request_fingerprint") or "").strip()
    if fingerprint:
        st.write("DOR har et aktivt, backend-registreret arbejdsgrundlag for projektet.")
        st.caption("Den fulde Plan kan ikke læses gennem en canonical backend-kontrakt i denne version.")
    else:
        st.info("Der er endnu ikke registreret et aktivt arbejdsgrundlag.")

    st.markdown("### Proposal")
    if not proposals:
        st.caption("Der er endnu ikke et Proposal knyttet til den aktuelle Execution.")
    for proposal in proposals:
        with st.container(border=True):
            st.markdown(f"**{proposal.get('title') or 'Forslag'}**")
            if proposal.get("summary"):
                st.write(proposal["summary"])
            _render_provenance(project, execution, proposal)

    st.markdown("### Evidens")
    verified = completion_evidence(project)
    if verified:
        for item in verified:
            st.success(item["label"])
            st.caption(f"Bevis: {item['record_id']}")
    else:
        st.caption("Der er endnu ikke et autoritativt afslutningsbevis for projektet.")
    st.caption("Pipeline-status forklarer fremdrift, men præsenteres ikke som Proposal-specifikt bevis uden en backend-relation.")

    _render_provenance(project, execution)


def _handle_decision_error(exc: DORAPIError) -> None:
    if exc.status_code == 401:
        _clear_auth()
        st.error("Din session er udløbet. Log ind igen.")
    elif exc.status_code == 403:
        st.error("Backend afviste beslutningen. Du har ikke den nødvendige autorisation.")
    elif exc.status_code == 409:
        st.warning("Beslutningen er ikke længere aktuel eller er allerede behandlet. Hent status igen.")
    else:
        st.error("Beslutningen kunne ikke registreres. DOR har ikke rapporteret succes.")


def _render_gate_card(api: CustomerAPI, workflow_id: str, gate: dict[str, Any]) -> None:
    actions = decision_actions(gate)
    if not actions:
        return
    with st.container(border=True):
        st.markdown(f"**{gate.get('name') or 'Beslutning'}**")
        st.write(gate.get("description") or "DOR har brug for din beslutning.")
        st.caption(f"Gate ID: {gate.get('id')}")

        if "approve" in actions:
            approve, reject = st.columns(2)
            with approve:
                if st.button("Godkend", key=f"customer-approve-{workflow_id}-{gate['id']}", type="primary", use_container_width=True):
                    try:
                        api.decide(workflow_id, str(gate["id"]), "approved")
                    except DORAPIError as exc:
                        _handle_decision_error(exc)
                    except CustomerContractError:
                        st.error(UNKNOWN_STATUS)
                    else:
                        st.success("Beslutningen er registreret. DOR henter authoritative status igen.")
                        st.rerun()
            with reject:
                if st.button("Afvis", key=f"customer-reject-{workflow_id}-{gate['id']}", use_container_width=True):
                    try:
                        api.decide(workflow_id, str(gate["id"]), "rejected")
                    except DORAPIError as exc:
                        _handle_decision_error(exc)
                    except CustomerContractError:
                        st.error(UNKNOWN_STATUS)
                    else:
                        st.warning("Afvisningen er registreret. DOR fortsætter ikke på grundlag af denne gate-beslutning.")
                        st.rerun()

        if "request_changes" in actions:
            reason = st.text_area(
                "Hvad skal ændres?",
                key=f"customer-rework-reason-{workflow_id}-{gate['id']}",
                max_chars=2000,
            )
            if st.button("Bed om ændringer", key=f"customer-rework-{workflow_id}-{gate['id']}", type="primary"):
                try:
                    api.request_changes(workflow_id, str(gate["id"]), reason)
                except ValueError:
                    st.warning("Beskriv de ønskede ændringer først.")
                except DORAPIError as exc:
                    _handle_decision_error(exc)
                except CustomerContractError:
                    st.error(UNKNOWN_STATUS)
                else:
                    st.success("Ændringsønsket er registreret. DOR henter authoritative status igen.")
                    st.rerun()


def _all_runtime(api: CustomerAPI, projects: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]]:
    result = []
    for project in projects:
        try:
            execution, gates, proposals = _project_runtime(api, project)
        except (DORAPIError, CustomerContractError):
            execution, gates, proposals = None, [], []
        result.append((project, execution, gates, proposals))
    return result


def _dashboard(api: CustomerAPI, projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">OVERBLIK</div>', unsafe_allow_html=True)
    st.title("Er der noget, jeg skal gøre?")
    runtime = _all_runtime(api, projects)
    attention = [item for item in runtime if any(decision_actions(gate) for gate in item[2])]
    a, b = st.columns(2)
    a.metric("Projekter", len(projects))
    b.metric("Kræver din opmærksomhed", len(attention))
    if attention:
        st.markdown("### Din opmærksomhed")
        for project, execution, gates, _ in attention:
            workflow_id = str((execution or {}).get("workflow_id") or "")
            st.markdown(f"#### {project.get('name') or project.get('project_id')}")
            for gate in gates:
                _render_gate_card(api, workflow_id, gate)
    else:
        st.info("DOR har ikke rapporteret en beslutning, der kræver din handling lige nu.")

    st.markdown("### Projekter")
    for project, execution, _, _ in runtime:
        status = customer_execution_status(execution).label if execution is not None else "Ikke startet"
        with st.container(border=True):
            st.markdown(f"**{project.get('name') or project.get('project_id')}**")
            st.caption(f"{project.get('status') or UNKNOWN_STATUS} · {status}")


def _projects_view(api: CustomerAPI, projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">PROJEKTER</div>', unsafe_allow_html=True)
    st.title("Dine projekter")
    if not projects:
        st.info("Der er ingen projekter i din authenticated organisation.")
        return
    by_id = {str(item["project_id"]): item for item in projects}
    selected = st.selectbox(
        "Projekt",
        list(by_id),
        format_func=lambda value: str(by_id[value].get("name") or value),
        key="customer_project_id",
    )
    _render_project(api, by_id[selected])


def _decisions_view(api: CustomerAPI, projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">BESLUTNINGSCENTER</div>', unsafe_allow_html=True)
    st.title("Beslutninger")
    shown = 0
    for project, execution, gates, _ in _all_runtime(api, projects):
        if execution is None:
            continue
        actionable = [gate for gate in gates if decision_actions(gate)]
        if not actionable:
            continue
        st.markdown(f"### {project.get('name') or project.get('project_id')}")
        workflow_id = str(execution.get("workflow_id") or "")
        for gate in actionable:
            shown += 1
            _render_gate_card(api, workflow_id, gate)
    if shown == 0:
        st.info("Der er ingen backend-rapporterede beslutninger, der kræver handling.")
    st.caption("Knapper i portalen er ikke autorisation. Backend genvaliderer hver beslutningskommando.")


def _history_view(api: CustomerAPI, organization: Mapping[str, Any], projects: list[dict[str, Any]]) -> None:
    st.markdown('<div class="eyebrow">AKTIVITET</div>', unsafe_allow_html=True)
    st.title("Historik")
    organization_id = str(organization.get("id") or "")
    any_event = False
    for project in projects:
        project_id = str(project.get("project_id") or "")
        try:
            events = api.project_events(project_id, organization_id)
        except (DORAPIError, CustomerContractError):
            st.warning(f"Historikken for {project.get('name') or project_id} kunne ikke fastslås.")
            continue
        if not events:
            continue
        any_event = True
        st.markdown(f"### {project.get('name') or project_id}")
        for event in reversed(events):
            with st.container(border=True):
                st.markdown(f"**{event.get('event_type') or 'Event'}**")
                st.caption(str(event.get("occurred_at") or "Tidspunkt ikke oplyst"))
                with st.expander("Vis detaljer"):
                    st.write(f"Event ID: `{event.get('event_id') or '—'}`")
                    st.write(f"Actor: `{event.get('actor_id') or '—'}`")
                    if isinstance(event.get("metadata"), Mapping):
                        st.json(dict(event["metadata"]))
    st.markdown("### Beslutningshistorik")
    any_decision = False
    for project, execution, gates, _ in _all_runtime(api, projects):
        if execution is None:
            continue
        resolved = [gate for gate in gates if gate.get("resolved") is True]
        if not resolved:
            continue
        any_decision = True
        st.markdown(f"#### {project.get('name') or project.get('project_id')}")
        for gate in resolved:
            with st.container(border=True):
                decision = str(gate.get("decision") or UNKNOWN_STATUS)
                st.markdown(f"**{gate.get('name') or 'Beslutning'}**")
                st.write(f"Resultat: {decision}")
                st.caption(f"Gate ID: {gate.get('id') or '—'} · Runde: {gate.get('round') or '—'}")
    if not any_event:
        st.info("Der er ingen authoritative project events at vise endnu.")
    if not any_decision:
        st.caption("Der er ingen resolved gates i den aktuelle backend-projektion.")
    st.caption("Execution-gate kontrakten eksponerer resolved gates, men ikke en komplet persisted, tidsstemplet decision-ledger i denne version.")


def main() -> None:
    _css()
    if not st.session_state.get("customer_access_token"):
        _login()
        return

    nav = _sidebar()
    api = _api()
    loaded = _load_projects(api)
    if loaded is None:
        return
    organization, projects = loaded

    if nav == "Dashboard":
        _dashboard(api, projects)
    elif nav == "Projekter":
        _projects_view(api, projects)
    elif nav == "Beslutninger":
        _decisions_view(api, projects)
    elif nav == "Historik":
        _history_view(api, organization, projects)


if __name__ == "__main__":
    main()
