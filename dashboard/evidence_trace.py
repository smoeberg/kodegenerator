"""Streamlit renderer for the execution Why / Evidence Trace."""
from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.cockpit_view_model import build_evidence_trace


def _stage_caption(stage: dict) -> str:
    return f"**{stage['label']}**\n\n{stage['count']} evidence item(s)"


def render_evidence_trace(client: DORAPIClient, workflow_id: str) -> None:
    """Render a read-only provenance view from canonical Execution API data."""
    st.divider()
    st.subheader("🔎 Why / Evidence Trace")
    st.write(
        "**Hvorfor er workflowet her?** Trace'et samler den evidens, som den "
        "kanoniske Execution API faktisk eksponerer — uden at opfinde manglende links."
    )

    try:
        execution_payload = client.get(f"/api/v1/execution/{workflow_id}")
        gates_payload = client.get(f"/api/v1/execution/{workflow_id}/gates")
        proposals_payload = client.get(f"/api/v1/execution/{workflow_id}/proposals")
    except DORAPIError as exc:
        if exc.status_code == 401:
            raise
        st.caption(f"Evidence trace ikke tilgængeligt ({exc.status_code}): {exc}")
        return

    trace = build_evidence_trace(
        execution_payload,
        gates_payload,
        proposals_payload,
    )

    st.caption(
        f"Workflow `{trace['workflow_id']}` · current state `{trace['current_state']}`"
    )

    stage_cols = st.columns(len(trace["stages"]))
    for column, stage in zip(stage_cols, trace["stages"]):
        column.markdown(_stage_caption(stage))

    st.caption(
        " → ".join(stage["label"] for stage in trace["stages"])
    )

    workflow_scope_links = [
        key
        for key, value in trace["linkage"].items()
        if value == "workflow_scope"
    ]
    if workflow_scope_links:
        st.info(
            "Nogle led er kun dokumenteret på workflow-niveau: "
            + ", ".join(workflow_scope_links)
            + ". Det er bevidst markeret som workflow_scope."
        )

    with st.expander("1 · Requirements", expanded=True):
        if not trace["requirements"]:
            st.caption("Ingen requirements eksponeret i workflow context.")
        for requirement in trace["requirements"]:
            st.markdown(f"**{requirement['id']}** — {requirement['description'] or 'Ingen beskrivelse'}")
            if requirement["acceptance_criteria"]:
                for criterion in requirement["acceptance_criteria"]:
                    st.write(f"- {criterion}")
            st.caption(f"Linkage: `{requirement['linkage']}`")

    with st.expander("2 · Tasks"):
        if trace["tasks"]:
            st.dataframe(trace["tasks"], use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen pipeline-tasks eksponeret af Execution API.")

    with st.expander("3 · Agent work"):
        st.caption(
            "Execution API eksponerer task execution, men ikke en særskilt agent-identitet/"
            "resultat-record pr. pipeline-task. Derfor vises kun verificerbar task-evidens."
        )
        if trace["agent_work"]:
            st.dataframe(trace["agent_work"], use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen agent-work-evidens kan afledes fra tasks endnu.")

    with st.expander("4 · Proposals"):
        if trace["proposals"]:
            st.dataframe(trace["proposals"], use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen implementation proposals rapporteret.")

    with st.expander("5 · Tests"):
        test_cols = st.columns(3)
        test_cols[0].metric("Tests generated", "ja" if trace["tests"]["tests_generated"] else "nej")
        test_cols[1].metric("Tests passed", "ja" if trace["tests"]["tests_passed"] else "nej")
        test_cols[2].metric("Test tasks", len(trace["tests"]["tasks"]))
        if trace["tests"]["error"]:
            st.error(f"Test/execution error: {trace['tests']['error']}")
        if trace["tests"]["tasks"]:
            st.dataframe(trace["tests"]["tasks"], use_container_width=True, hide_index=True)

    with st.expander("6 · Gates"):
        if trace["gates"]:
            st.dataframe(trace["gates"], use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen quality gates rapporteret.")

    with st.expander("7 · Human decisions", expanded=True):
        if trace["decisions"]:
            st.dataframe(trace["decisions"], use_container_width=True, hide_index=True)
        else:
            st.caption("Ingen menneskelige gate-beslutninger registreret endnu.")

    with st.expander("Provenance-kvalitet & kendte gaps"):
        st.json(trace["linkage"])
        for gap in trace["gaps"]:
            st.write(f"- {gap}")
