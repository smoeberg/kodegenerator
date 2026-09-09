"""Human-facing case views shared by the DOR operator shell."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_process_projection import AttentionState
from dashboard.case_shell_actions import (
    create_case_form,
    evidence_lookup,
    render_evidence_summary,
    render_execution_detail,
    render_gate_actions,
    render_project_lifecycle_tools,
    render_technical_case_details,
    should_render_gate_actions,
    stop_realtime,
)
from dashboard.case_workbench import (
    CaseWorkbenchItem,
    CaseWorkbenchSnapshot,
    find_case,
    overview_counts,
)


def greeting() -> str:
    hour = datetime.now(ZoneInfo("Europe/Copenhagen")).hour
    if 5 <= hour < 12:
        return "Godmorgen"
    if 12 <= hour < 18:
        return "Goddag"
    return "Godaften"


def metric(label: str, value: object, foot: str) -> None:
    st.markdown(
        f'<div class="card metric"><div class="metric-label">{label}</div>'
        f'<div class="metric-value">{value}</div><div class="metric-foot">{foot}</div></div>',
        unsafe_allow_html=True,
    )


def open_case(case_id: str) -> None:
    st.session_state["selected_project_id"] = case_id
    st.session_state["operator_nav"] = "Sager"
    st.session_state["operator_admin_nav"] = "Ingen"
    st.rerun()


def render_process(item: CaseWorkbenchItem) -> None:
    html = '<div class="lifecycle">'
    for index, step in enumerate(item.projection.process_steps, start=1):
        status = step["status"]
        css_class = (
            "done" if status == "completed" else "current" if status == "active" else ""
        )
        mark = "✓" if status == "completed" else str(index)
        html += (
            f'<div class="life {css_class}"><div class="life-dot">{mark}</div>'
            f'{step["label"]}</div>'
        )
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def render_attention(item: CaseWorkbenchItem) -> None:
    projection = item.projection
    if projection.attention_required:
        st.markdown(
            '<span class="status-pill">Kræver opmærksomhed</span>',
            unsafe_allow_html=True,
        )
    st.markdown(
        f'<div class="attention"><b>{projection.attention_title}</b><br>'
        f'{projection.attention_explanation}</div>',
        unsafe_allow_html=True,
    )
    if projection.next_action:
        st.write("")
        st.markdown(f"**Næste handling:** {projection.next_action.label}")
        st.caption(projection.next_action.explanation)
    elif projection.owner_type == "dor":
        st.caption("DOR har bolden. Du skal ikke gøre noget lige nu.")
    elif projection.attention_required:
        st.caption("Åbn Handling nedenfor. Mutationen vises kun, når backend tillader den.")


def overview(
    client: DORAPIClient,
    snapshot: CaseWorkbenchSnapshot,
    execution_error: str | None,
) -> None:
    counts = overview_counts(snapshot)
    focus = next(
        iter(snapshot.requiring_action),
        next(iter(snapshot.waiting_for_dor), next(iter(snapshot.cases), None)),
    )

    st.markdown(
        f'<div class="eyebrow">OPERATØRCENTER / OVERBLIK</div>'
        f'<h1>{greeting()}, {st.session_state.get("username") or "operatør"}</h1>'
        '<div class="subtitle">Her er det, der kræver din opmærksomhed først.</div>',
        unsafe_allow_html=True,
    )
    if execution_error:
        st.markdown(
            f'<div class="warning"><b>Execution-data er midlertidigt utilgængelige.</b><br>'
            f'{execution_error} Sager uden execution kan stadig vises.</div>',
            unsafe_allow_html=True,
        )
        st.write("")

    cols = st.columns(4)
    with cols[0]:
        metric("Kræver din handling", counts["requires_action"], "Prioriterede sager")
    with cols[1]:
        metric("Afventer DOR", counts["waiting_for_dor"], "DOR har bolden")
    with cols[2]:
        metric("Afventer andre", counts["waiting_external"], "Ekstern afhængighed")
    with cols[3]:
        metric("Færdige", counts["completed"], f'{counts["cases"]} sager i alt')

    left, right = st.columns([2.1, 1])
    with left:
        if focus:
            with st.container(border=True):
                st.caption(focus.projection.phase.label)
                st.subheader(focus.projection.title)
                st.caption(focus.projection.human_status)
                render_process(focus)
                render_attention(focus)
                if st.button("Åbn sag", type="primary", use_container_width=True):
                    open_case(focus.projection.case_id)
        else:
            st.info("Der er ingen sager endnu.")
            if st.button("Opret første sag", type="primary"):
                st.session_state["operator_nav"] = "Sager"
                st.rerun()

    with right:
        st.markdown(
            '<div class="card"><div class="eyebrow">SYSTEMHELDBRED</div><h2>Systemstatus</h2>',
            unsafe_allow_html=True,
        )
        try:
            ready = client.readiness()
            state = ready.get("status", "unknown") if isinstance(ready, dict) else "unknown"
            st.metric("API / database", str(state).upper())
        except DORAPIError as exc:
            st.error(f"Readiness ({exc.status_code})")
        st.caption("Systemstatus er sekundær; sagens situation og næste handling er primær.")
        st.markdown("</div>", unsafe_allow_html=True)

    st.write("")
    st.subheader("Kræver opmærksomhed")
    if snapshot.requiring_action:
        for item in snapshot.requiring_action[:6]:
            cols = st.columns([4, 1])
            with cols[0]:
                st.markdown(f"**{item.projection.title}**")
                st.caption(
                    f"{item.projection.phase.label} · {item.projection.attention_title}"
                )
            with cols[1]:
                if st.button(
                    "Åbn",
                    key=f"overview-open-{item.projection.case_id}",
                    use_container_width=True,
                ):
                    open_case(item.projection.case_id)
    else:
        st.success("Ingen sager kræver din handling lige nu.")


def _work_group(
    title: str,
    items: tuple[CaseWorkbenchItem, ...],
    *,
    primary: bool,
) -> None:
    st.subheader(f"{title}  ·  {len(items)}")
    if not items:
        st.caption("Ingen sager i denne gruppe.")
        return
    for item in items:
        with st.container(border=True):
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f"**{item.projection.title}**")
                st.write(item.projection.attention_title)
                st.caption(f"{item.projection.phase.label} · {item.projection.human_status}")
                if item.projection.next_action:
                    st.caption(f"Næste: {item.projection.next_action.label}")
            with cols[1]:
                if st.button(
                    "Åbn sag",
                    key=f"work-open-{title}-{item.projection.case_id}",
                    type="primary" if primary else "secondary",
                    use_container_width=True,
                ):
                    open_case(item.projection.case_id)


def work_view(snapshot: CaseWorkbenchSnapshot) -> None:
    st.markdown(
        '<div class="eyebrow">OPERATØRCENTER / MIT ARBEJDE</div>'
        '<h1>Mit arbejde</h1>'
        '<div class="subtitle">Sager sorteret efter hvem der har bolden — ikke efter backend-modul.</div>',
        unsafe_allow_html=True,
    )
    _work_group("Kræver din handling", snapshot.requiring_action, primary=True)
    st.write("")
    _work_group("Afventer DOR", snapshot.waiting_for_dor, primary=False)
    st.write("")
    _work_group("Afventer andre", snapshot.waiting_external, primary=False)
    st.write("")
    _work_group("Færdig", snapshot.completed, primary=False)


def cases_view(client: DORAPIClient, snapshot: CaseWorkbenchSnapshot) -> None:
    st.markdown(
        '<div class="eyebrow">OPERATØRCENTER / SAGER</div>'
        '<h1>Sager</h1>'
        '<div class="subtitle">Status, proces, næste handling og evidens samlet i én kontekst.</div>',
        unsafe_allow_html=True,
    )
    create_case_form(client)
    if not snapshot.cases:
        st.info("Der er ingen sager at vise endnu.")
        return

    case_ids = [item.projection.case_id for item in snapshot.cases]
    selected_id = st.session_state.get("selected_project_id")
    if selected_id not in case_ids:
        selected_id = case_ids[0]
        st.session_state["selected_project_id"] = selected_id
    index = case_ids.index(selected_id)

    def _case_label(case_id: str) -> str:
        item = find_case(snapshot, case_id)
        return item.projection.title if item else case_id

    selected_id = st.selectbox(
        "Vælg sag",
        case_ids,
        index=index,
        format_func=_case_label,
    )
    st.session_state["selected_project_id"] = selected_id
    item = find_case(snapshot, selected_id)
    if item is None:
        st.error("Sagen kunne ikke projiceres fra det aktuelle backend-snapshot.")
        return

    projection = item.projection
    st.caption(projection.phase.label)
    st.title(projection.title)
    st.caption(projection.human_status)
    render_process(item)

    st.subheader("Næste skridt")
    render_attention(item)

    st.subheader("Handling")
    if should_render_gate_actions(item):
        render_gate_actions(client, item)
    elif projection.owner_type == "dor":
        st.info("DOR arbejder. Der kræves ingen human handling lige nu.")
    elif projection.attention_state in {
        AttentionState.COMPLETED,
        AttentionState.CANCELLED,
        AttentionState.ARCHIVED,
    }:
        st.info("Sagen er terminal. Eventuelle lifecycle-handlinger vises kun som avancerede handlinger.")
    else:
        st.info("Backend har ikke åbnet en human gate for det aktuelle snapshot.")

    st.subheader("Evidens")
    render_evidence_summary(item)

    with st.expander("Tekniske detaljer"):
        render_technical_case_details(client, item)

    render_project_lifecycle_tools(client, item)

    technical_workflow_id = str(st.session_state.get("technical_workflow_id") or "").strip()
    if technical_workflow_id:
        st.divider()
        cols = st.columns([4, 1])
        with cols[0]:
            st.subheader("Teknisk execution-visning")
        with cols[1]:
            if st.button("Luk", key="close-case-technical", use_container_width=True):
                st.session_state.pop("technical_workflow_id", None)
                stop_realtime()
                st.rerun()
        render_execution_detail(client, technical_workflow_id)


def search_view(client: DORAPIClient, snapshot: CaseWorkbenchSnapshot) -> None:
    st.markdown(
        '<div class="eyebrow">OPERATØRCENTER / SØG</div>'
        '<h1>Søg</h1>'
        '<div class="subtitle">Find sag, status eller — ved behov — en teknisk reference.</div>',
        unsafe_allow_html=True,
    )
    query = st.text_input("Søg i sager", placeholder="Navn, status, fase eller ID")
    normalized = query.strip().casefold()

    if normalized:
        matches: list[CaseWorkbenchItem] = []
        for item in snapshot.cases:
            projection = item.projection
            haystack = [
                projection.case_id,
                projection.title,
                projection.phase.label,
                projection.human_status,
                projection.attention_title,
                *[str(value or "") for value in projection.technical_refs.values()],
            ]
            if any(normalized in value.casefold() for value in haystack):
                matches.append(item)

        st.subheader(f"Sager · {len(matches)}")
        for item in matches:
            cols = st.columns([5, 1])
            with cols[0]:
                st.markdown(f"**{item.projection.title}**")
                st.caption(f"{item.projection.phase.label} · {item.projection.human_status}")
            with cols[1]:
                if st.button(
                    "Åbn",
                    key=f"search-open-{item.projection.case_id}",
                    use_container_width=True,
                ):
                    open_case(item.projection.case_id)

        legacy_matches = [
            execution
            for execution in snapshot.unlinked_executions
            if normalized
            in " ".join(
                str(execution.get(key) or "")
                for key in ("workflow_id", "project_name", "current_state")
            ).casefold()
        ]
        if legacy_matches:
            st.subheader("Tekniske executions uden Sag")
            st.caption(
                "Disse har ingen eksplicit backend project_id-relation. DOR opfinder ikke provenance."
            )
            for execution in legacy_matches:
                workflow_id = str(execution.get("workflow_id") or "").strip()
                if not workflow_id:
                    continue
                cols = st.columns([5, 1])
                with cols[0]:
                    st.markdown(f"**{execution.get('project_name') or 'Unlinked execution'}**")
                    st.caption(f"{execution.get('current_state') or 'unknown'} · workflow {workflow_id}")
                with cols[1]:
                    if st.button(
                        "Åbn teknisk",
                        key=f"search-legacy-{workflow_id}",
                        use_container_width=True,
                    ):
                        st.session_state["technical_workflow_id"] = workflow_id
                        st.rerun()
    else:
        st.caption("Skriv et søgeord for at finde en sag.")

    technical_workflow_id = str(st.session_state.get("technical_workflow_id") or "").strip()
    if technical_workflow_id:
        st.divider()
        cols = st.columns([4, 1])
        with cols[0]:
            st.subheader("Teknisk execution-visning")
        with cols[1]:
            if st.button("Luk", key="close-search-technical", use_container_width=True):
                st.session_state.pop("technical_workflow_id", None)
                stop_realtime()
                st.rerun()
        render_execution_detail(client, technical_workflow_id)

    with st.expander("Specialist: teknisk evidensopslag"):
        evidence_lookup(client)
