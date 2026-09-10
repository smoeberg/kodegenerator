"""Human-facing case views shared by the DOR operator shell."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_clarification import render_case_clarification
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
from dashboard.workbench_guidance import case_status_badge, primary_action_text


def greeting() -> str:
    hour = datetime.now(ZoneInfo("Europe/Copenhagen")).hour
    if 5 <= hour < 12:
        return "Godmorgen"
    if 12 <= hour < 18:
        return "Goddag"
    return "Godaften"


def open_case(case_id: str) -> None:
    st.session_state["selected_project_id"] = case_id
    st.session_state["operator_nav"] = "Sager"
    st.session_state["operator_admin_nav"] = "Ingen"
    st.rerun()


def _go_to(nav: str) -> None:
    st.session_state["operator_nav"] = nav
    st.session_state["operator_admin_nav"] = "Ingen"
    st.rerun()


def _owner_label(item: CaseWorkbenchItem) -> str:
    return {
        "human": "Dig",
        "dor": "DOR",
        "external": "En ekstern part",
        "none": "Ingen",
    }.get(item.projection.owner_type, "Ukendt")


def _activity_copy(item: CaseWorkbenchItem) -> tuple[str, str]:
    projection = item.projection
    if projection.attention_state in {
        AttentionState.COMPLETED,
        AttentionState.CANCELLED,
        AttentionState.ARCHIVED,
    }:
        return ("Arbejdet er afsluttet", "Der er ingen aktiv aktivitet på sagen.")
    if projection.owner_type == "dor":
        return (
            "DOR arbejder videre",
            projection.attention_explanation or "Du skal ikke gøre noget lige nu.",
        )
    if projection.owner_type == "external":
        return (
            "Sagen afventer andre",
            projection.attention_explanation
            or "DOR fortsætter, når den eksterne afhængighed er afklaret.",
        )
    if projection.attention_required:
        return (
            "Sagen afventer dig",
            projection.attention_explanation
            or "Din handling er nødvendig, før processen kan fortsætte.",
        )
    return (
        "Klar til næste skridt",
        projection.attention_explanation or "Backend har ikke markeret en aktiv blocker.",
    )


def _render_status_badge(item: CaseWorkbenchItem) -> None:
    badge = case_status_badge(item.projection)
    css_class = "" if badge.tone == "attention" else " quiet-pill"
    st.markdown(
        f'<span class="status-pill{css_class}">{badge.label}</span>',
        unsafe_allow_html=True,
    )


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
    _render_status_badge(item)
    st.markdown(
        f'<div class="attention"><div class="attention-kicker">NÆSTE SKRIDT</div>'
        f'<div class="attention-title">{projection.attention_title}</div>'
        f'<div class="attention-copy">{projection.attention_explanation}</div></div>',
        unsafe_allow_html=True,
    )

    if projection.next_action:
        st.markdown(
            f'<div class="next-action"><div class="next-action-label">'
            f'{projection.next_action.label}</div>'
            f'<div class="next-action-why">Hvorfor dette er næste skridt: '
            f'{projection.next_action.explanation}</div></div>',
            unsafe_allow_html=True,
        )
    elif projection.owner_type == "dor":
        st.caption(
            "Du skal ikke gøre noget nu. DOR genberegner næste handling, når arbejdet ændrer state."
        )
    elif projection.attention_required:
        st.caption("Handlingen vises nedenfor, når backend eksplicit tillader den.")


def _render_quick_starts() -> None:
    st.markdown(
        '<div class="section-label">HVAD VIL DU GØRE?</div>', unsafe_allow_html=True
    )
    cols = st.columns(3)
    with cols[0]:
        if st.button("＋ Opret en sag", use_container_width=True):
            _go_to("Sager")
        st.caption("Beskriv situationen og det ønskede resultat.")
    with cols[1]:
        if st.button("Se mit arbejde", use_container_width=True):
            _go_to("Mit arbejde")
        st.caption("Se kun det, der kræver dig eller afventer andre.")
    with cols[2]:
        if st.button("Find en sag", use_container_width=True):
            _go_to("Søg")
        st.caption("Søg på navn, status, fase eller reference.")


def _render_system_details(client: DORAPIClient, execution_error: str | None) -> None:
    with st.expander("Systemoplysninger"):
        st.caption("Teknisk drift er sekundær i den normale arbejdsoplevelse.")
        try:
            ready = client.readiness()
            state = ready.get("status", "unknown") if isinstance(ready, dict) else "unknown"
            st.write(f"**API / database:** {str(state).upper()}")
        except DORAPIError as exc:
            st.write(f"**API / database:** utilgængelig ({exc.status_code})")
        if execution_error:
            st.warning(execution_error)


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
        f'<div class="eyebrow">DOR / GUIDE</div>'
        f'<h1>{greeting()}, {st.session_state.get("username") or "operatør"}</h1>'
        '<div class="hero-question">Hvad vil du gøre?</div>'
        '<div class="subtitle">DOR viser situationen og det vigtigste næste skridt — ikke backend-moduler.</div>',
        unsafe_allow_html=True,
    )

    _render_quick_starts()
    st.write("")

    if focus:
        projection = focus.projection
        st.markdown(
            '<div class="section-label">DET VIGTIGSTE NU</div>', unsafe_allow_html=True
        )
        with st.container(border=True):
            top_left, top_right = st.columns([4, 1.2])
            with top_left:
                st.caption(f"{projection.phase.label} · {_owner_label(focus)} har bolden")
                st.subheader(projection.title)
                st.write(projection.human_status)
            with top_right:
                _render_status_badge(focus)

            render_attention(focus)
            render_process(focus)
            if st.button(
                "Åbn sagen og fortsæt",
                key=f"overview-focus-{projection.case_id}",
                type="primary",
                use_container_width=True,
            ):
                open_case(projection.case_id)
    else:
        st.markdown('<div class="section-label">KOM I GANG</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.subheader("Fortæl DOR, hvad der skal ske")
            st.write(
                "Der er ingen sager endnu. Opret den første sag ud fra målet — "
                "DOR holder styr på proces, handlinger og evidens."
            )
            if st.button("Opret første sag", type="primary"):
                _go_to("Sager")

    st.write("")
    st.markdown('<div class="section-label">DIT ARBEJDE</div>', unsafe_allow_html=True)
    summary_cols = st.columns(4)
    summary_cols[0].metric("Kræver dig", counts["requires_action"])
    summary_cols[1].metric("DOR arbejder", counts["waiting_for_dor"])
    summary_cols[2].metric("Afventer andre", counts["waiting_external"])
    summary_cols[3].metric("Færdige", counts["completed"])

    if snapshot.requiring_action:
        st.subheader("Andre sager der kræver dig")
        for item in snapshot.requiring_action:
            if focus and item.projection.case_id == focus.projection.case_id:
                continue
            cols = st.columns([5, 1])
            with cols[0]:
                _render_status_badge(item)
                st.markdown(f"**{item.projection.title}**")
                st.caption(
                    f"{item.projection.phase.label} · Næste: {primary_action_text(item.projection)}"
                )
            with cols[1]:
                if st.button(
                    "Åbn",
                    key=f"overview-open-{item.projection.case_id}",
                    use_container_width=True,
                ):
                    open_case(item.projection.case_id)

    st.write("")
    _render_system_details(client, execution_error)


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
    for index, item in enumerate(items):
        with st.container(border=True):
            cols = st.columns([5, 1])
            with cols[0]:
                _render_status_badge(item)
                st.markdown(f"**{item.projection.title}**")
                st.write(item.projection.attention_title)
                st.caption(
                    f"{item.projection.phase.label} · Næste: {primary_action_text(item.projection)}"
                )
            with cols[1]:
                if st.button(
                    "Åbn sag",
                    key=f"work-open-{title}-{item.projection.case_id}",
                    type="primary" if primary and index == 0 else "secondary",
                    use_container_width=True,
                ):
                    open_case(item.projection.case_id)


def work_view(snapshot: CaseWorkbenchSnapshot) -> None:
    st.markdown(
        '<div class="eyebrow">DOR / MIT ARBEJDE</div>'
        '<h1>Mit arbejde</h1>'
        '<div class="subtitle">Hvem har bolden, og hvad kræver din opmærksomhed?</div>',
        unsafe_allow_html=True,
    )
    _work_group("Kræver din handling", snapshot.requiring_action, primary=True)
    st.write("")
    _work_group("DOR arbejder", snapshot.waiting_for_dor, primary=False)
    st.write("")
    _work_group("Afventer andre", snapshot.waiting_external, primary=False)
    st.write("")
    _work_group("Færdig", snapshot.completed, primary=False)


def _render_case_action(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    projection = item.projection
    if should_render_gate_actions(item):
        render_gate_actions(client, item)
    elif projection.owner_type == "dor":
        st.info("DOR arbejder videre. Der kræves ingen handling fra dig lige nu.")
    elif projection.attention_state in {
        AttentionState.COMPLETED,
        AttentionState.CANCELLED,
        AttentionState.ARCHIVED,
    }:
        st.info(
            "Sagen er afsluttet. Eventuelle administrative lifecycle-handlinger ligger under Flere muligheder."
        )
    elif projection.attention_required:
        st.info("DOR har endnu ikke åbnet en konkret handling for denne situation.")
    else:
        st.info("Der er ingen åben handling lige nu.")


def _select_case(snapshot: CaseWorkbenchSnapshot, selected_id: str) -> None:
    st.markdown('<div class="section-label">SAGER</div>', unsafe_allow_html=True)
    for candidate in snapshot.cases:
        candidate_id = candidate.projection.case_id
        selected = candidate_id == selected_id
        label = f"● {candidate.projection.title}" if selected else candidate.projection.title
        if st.button(
            label,
            key=f"case-picker-{candidate_id}",
            use_container_width=True,
        ) and not selected:
            st.session_state["selected_project_id"] = candidate_id
            st.rerun()
        badge = case_status_badge(candidate.projection)
        st.caption(f"{badge.label} · {candidate.projection.phase.label}")


def _render_case_detail(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    projection = item.projection
    _render_status_badge(item)
    st.caption(f"{projection.phase.label} · {projection.human_status}")
    st.title(projection.title)

    main_col, context_col = st.columns([2.15, 1])
    with main_col:
        st.markdown(
            '<div class="section-label">NÆSTE HANDLING</div>', unsafe_allow_html=True
        )
        render_attention(item)
        st.write("")
        _render_case_action(client, item)

    with context_col:
        st.markdown('<div class="section-label">SITUATION</div>', unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown(f"**Bolden er hos:** {_owner_label(item)}")
            st.write(projection.attention_title)
            st.caption(projection.attention_explanation)
            if projection.blockers:
                st.markdown("**Det blokerer sagen:**")
                for blocker in projection.blockers:
                    label = (
                        blocker.get("label")
                        or blocker.get("reason")
                        or blocker.get("id")
                        or "Ukendt blocker"
                    )
                    st.write(f"- {label}")
            elif projection.next_action:
                st.markdown("**Hvorfor dette er næste skridt**")
                st.caption(projection.next_action.explanation)

    st.write("")
    st.markdown('<div class="section-label">AFKLARING</div>', unsafe_allow_html=True)
    render_case_clarification(client, item)

    st.write("")
    activity_title, activity_detail = _activity_copy(item)
    st.markdown(
        '<div class="section-label">AKTUEL AKTIVITET</div>', unsafe_allow_html=True
    )
    with st.container(border=True):
        st.markdown(f"**{activity_title}**")
        st.write(activity_detail)
        if item.execution:
            task_rows = item.execution.get("tasks")
            if isinstance(task_rows, list) and task_rows:
                completed = sum(
                    1
                    for task in task_rows
                    if isinstance(task, dict)
                    and str(task.get("status") or "").lower()
                    in {"completed", "done", "success", "succeeded"}
                )
                st.caption(
                    f"{completed} af {len(task_rows)} registrerede aktiviteter er færdige."
                )

    st.markdown('<div class="section-label">PROCES</div>', unsafe_allow_html=True)
    render_process(item)

    st.markdown('<div class="section-label">EVIDENS</div>', unsafe_allow_html=True)
    render_evidence_summary(item)

    st.write("")
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


def cases_view(client: DORAPIClient, snapshot: CaseWorkbenchSnapshot) -> None:
    st.markdown(
        '<div class="eyebrow">DOR / SAG</div>'
        '<h1>Sag</h1>'
        '<div class="subtitle">Vælg en sag, se hvor den er, og gør kun det næste, som situationen kræver.</div>',
        unsafe_allow_html=True,
    )
    if not snapshot.cases:
        st.info("Der er ingen sager endnu. Opret den første sag ud fra det resultat, du vil opnå.")
        create_case_form(client, expanded=True)
        return

    create_case_form(client)
    case_ids = [item.projection.case_id for item in snapshot.cases]
    selected_id = st.session_state.get("selected_project_id")
    if selected_id not in case_ids:
        selected_id = case_ids[0]
        st.session_state["selected_project_id"] = selected_id

    item = find_case(snapshot, selected_id)
    if item is None:
        st.error("DOR kunne ikke vise den valgte sag fra det aktuelle snapshot. Hent siden igen.")
        return

    picker_col, detail_col = st.columns([1.05, 3.25], gap="large")
    with picker_col:
        _select_case(snapshot, selected_id)
    with detail_col:
        _render_case_detail(client, item)


def search_view(client: DORAPIClient, snapshot: CaseWorkbenchSnapshot) -> None:
    st.markdown(
        '<div class="eyebrow">DOR / SØG</div>'
        '<h1>Søg</h1>'
        '<div class="subtitle">Find en sag. Tekniske referencer er kun et specialistspor.</div>',
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
                _render_status_badge(item)
                st.markdown(f"**{item.projection.title}**")
                st.caption(
                    f"{item.projection.phase.label} · Næste: {primary_action_text(item.projection)}"
                )
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
                    st.markdown(
                        f"**{execution.get('project_name') or 'Unlinked execution'}**"
                    )
                    st.caption(
                        f"{execution.get('current_state') or 'unknown'} · workflow {workflow_id}"
                    )
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
