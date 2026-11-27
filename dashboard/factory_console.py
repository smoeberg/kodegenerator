"""Factory console: project overview, approval inbox and project configuration.

Completion plan, step 1 (GUI skeleton). The console is a thin client over the
pipeline API: it shows backend state and sends commands; it decides nothing.
Validation of backend payloads fails closed with ``FactoryConsoleError``.

The three areas follow the plan's GUI section:

* Projektoverblik: pipelines, state, requirements revision, tasks, job records
  and artifact provenance.
* Godkendelsesindbakke: every pending gate across the organization's
  pipelines in one place, with approve and reject.
* Projektkonfiguration: start a pipeline from a kravspec, see the bound
  requirements revision and its history, and the kravspec itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from dashboard.api_client import DORAPIError


class FactoryConsoleError(RuntimeError):
    """A backend payload or call the console cannot trust."""


@dataclass(frozen=True)
class PipelineRow:
    workflow_id: str
    name: str
    project_name: str
    state: str
    updated_at: str


@dataclass(frozen=True)
class InboxItem:
    workflow_id: str
    project_name: str
    state: str
    gate_id: str
    gate_name: str
    description: str


# --------------------------------------------------------------------- #
# API access (validated, fail closed)
# --------------------------------------------------------------------- #
def _call(action: str, fn, *args, **kwargs) -> Any:
    try:
        return fn(*args, **kwargs)
    except DORAPIError as exc:
        raise FactoryConsoleError(
            f"{action} fejlede ({exc.status_code}): {exc}"
        ) from exc


def list_pipelines(client: Any, organization_id: str) -> list[PipelineRow]:
    payload = _call(
        "Pipelines kunne ikke hentes",
        client.get,
        "/pipeline/",
        params={"organization_id": organization_id, "limit": 200},
    )
    if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
        raise FactoryConsoleError("Pipeline-listen er malformed")
    rows: list[PipelineRow] = []
    for item in payload["items"]:
        if not isinstance(item, Mapping) or not item.get("workflow_id"):
            raise FactoryConsoleError("Pipeline-listen indeholder en malformed post")
        rows.append(
            PipelineRow(
                workflow_id=str(item["workflow_id"]),
                name=str(item.get("name") or ""),
                project_name=str(item.get("project_name") or item.get("name") or ""),
                state=str(item.get("current_state") or "ukendt"),
                updated_at=str(item.get("updated_at") or ""),
            )
        )
    return sorted(rows, key=lambda row: row.updated_at, reverse=True)


def pipeline_status(
    client: Any, organization_id: str, workflow_id: str
) -> dict[str, Any]:
    payload = _call(
        "Pipeline-status kunne ikke hentes",
        client.get,
        f"/pipeline/{workflow_id}",
        params={"organization_id": organization_id},
    )
    if not isinstance(payload, Mapping) or payload.get("workflow_id") != workflow_id:
        raise FactoryConsoleError("Pipeline-status er malformed")
    return dict(payload)


def pipeline_gates(
    client: Any, organization_id: str, workflow_id: str
) -> list[dict[str, Any]]:
    payload = _call(
        "Gates kunne ikke hentes",
        client.get,
        f"/api/v1/pipeline-gates/{workflow_id}",
        params={"organization_id": organization_id},
    )
    if not isinstance(payload, list) or not all(
        isinstance(gate, Mapping) and gate.get("id") for gate in payload
    ):
        raise FactoryConsoleError("Gate-listen er malformed")
    return [dict(gate) for gate in payload]


def requirements_yaml(client: Any, organization_id: str, workflow_id: str) -> str:
    payload = _call(
        "Kravspec kunne ikke hentes",
        client.get,
        f"/pipeline/{workflow_id}/requirements",
        params={"organization_id": organization_id},
    )
    if not isinstance(payload, Mapping) or not isinstance(
        payload.get("requirements_yaml"), str
    ):
        raise FactoryConsoleError("Kravspec-svaret er malformed")
    return payload["requirements_yaml"]


def decide_gate(
    client: Any, organization_id: str, workflow_id: str, gate_id: str, *, approve: bool
) -> dict[str, Any]:
    payload = _call(
        "Gate-beslutningen kunne ikke sendes",
        client.post,
        "/api/v1/pipeline-gates/approve",
        params={"organization_id": organization_id},
        json={
            "workflow_id": workflow_id,
            "gate_id": gate_id,
            "decision": "approved" if approve else "rejected",
        },
    )
    if not isinstance(payload, Mapping) or payload.get("gate_id") != gate_id:
        raise FactoryConsoleError("Gate-svaret er malformed")
    return dict(payload)


def start_pipeline(
    client: Any, organization_id: str, kravspec_yaml: str
) -> dict[str, Any]:
    if not kravspec_yaml.strip():
        raise FactoryConsoleError("Kravspec er tom")
    payload = _call(
        "Pipelinen kunne ikke startes",
        client.post,
        "/pipeline/start",
        params={"organization_id": organization_id},
        json={"requirements_yaml": kravspec_yaml},
    )
    if not isinstance(payload, Mapping) or not payload.get("workflow_id"):
        raise FactoryConsoleError("Start-svaret er malformed")
    return dict(payload)


# --------------------------------------------------------------------- #
# View model (pure, testable)
# --------------------------------------------------------------------- #
def inbox_items(
    pipelines: list[PipelineRow],
    gates_by_workflow: Mapping[str, list[Mapping[str, Any]]],
) -> list[InboxItem]:
    """Every pending, unresolved gate across the pipelines, newest pipeline first."""
    items: list[InboxItem] = []
    for row in pipelines:
        for gate in gates_by_workflow.get(row.workflow_id, []):
            if gate.get("pending") and not gate.get("resolved"):
                items.append(
                    InboxItem(
                        workflow_id=row.workflow_id,
                        project_name=row.project_name,
                        state=row.state,
                        gate_id=str(gate["id"]),
                        gate_name=str(gate.get("name") or gate["id"]),
                        description=str(gate.get("description") or ""),
                    )
                )
    return items


def requirements_summary(status: Mapping[str, Any]) -> dict[str, Any] | None:
    """The bound requirements revision, or None for a pipeline without one."""
    ref = (status.get("context") or {}).get("requirements_ref")
    if not isinstance(ref, Mapping):
        return None
    return {
        "revision": ref.get("revision"),
        "declared_version": ref.get("declared_version") or "",
        "fingerprint": str(ref.get("fingerprint") or "")[:12],
        "requirement_ids": list(ref.get("requirement_ids") or []),
    }


def requirements_history(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    history = (status.get("context") or {}).get("requirements_history") or []
    return [
        {
            "revision": item.get("revision"),
            "fingerprint": str(item.get("fingerprint") or "")[:12],
            "superseded_by": item.get("superseded_by"),
            "superseded_at": item.get("superseded_at"),
        }
        for item in history
        if isinstance(item, Mapping)
    ]


def job_rows(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for job in status.get("jobs") or []:
        if not isinstance(job, Mapping):
            continue
        agent = job.get("agent") or {}
        requirements = job.get("requirements") or {}
        rows.append(
            {
                "rolle": job.get("role"),
                "opgavetype": job.get("task_type"),
                "forsøg": job.get("attempt"),
                "status": job.get("status"),
                "agent": agent.get("tool"),
                "producent": agent.get("brand") or "–",
                "kravspec-revision": requirements.get("revision"),
                "varighed (s)": job.get("duration_seconds"),
                "fejl": job.get("error") or "",
            }
        )
    return rows


def provenance_rows(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    provenance = (status.get("context") or {}).get("artifact_provenance") or {}
    rows = []
    for task_type, item in provenance.items():
        if not isinstance(item, Mapping):
            continue
        ref = item.get("requirements_ref") or {}
        rows.append(
            {
                "artefakt": task_type,
                "opgave": item.get("task_id"),
                "kravspec-revision": ref.get("revision"),
                "krav": ", ".join(ref.get("requirement_ids") or []),
                "resultatnøgler": ", ".join(item.get("result_keys") or []),
            }
        )
    return rows


def council_summary(status: Mapping[str, Any]) -> dict[str, Any] | None:
    """The architecture council's outcome, shown before the architecture gate."""
    council = ((status.get("context") or {}).get("architecture") or {}).get("council")
    if not isinstance(council, Mapping):
        return None
    proposal = council.get("proposal") or {}
    return {
        "status": council.get("status"),
        "rounds": len(council.get("rounds") or []),
        "roles": {
            role: f"{(identity or {}).get('brand')} · {(identity or {}).get('model')}"
            for role, identity in (council.get("roles") or {}).items()
        },
        "stack": proposal.get("stack") or {},
        "modules": [
            {
                "modul": module.get("id"),
                "ansvar": module.get("responsibility"),
                "krav": ", ".join(module.get("requirement_ids") or []),
                "afhænger af": ", ".join(module.get("depends_on") or []),
            }
            for module in proposal.get("modules") or []
        ],
        "build_layers": list(council.get("build_layers") or []),
        "open_findings": [
            {
                "kilde": item.get("source"),
                "alvor": item.get("severity"),
                "mål": item.get("target"),
                "fund": item.get("issue"),
            }
            for item in council.get("open_findings") or []
        ],
    }


def contract_council_summary(status: Mapping[str, Any]) -> dict[str, Any] | None:
    """The contract council's outcome, shown before the contracts gate."""
    contracts = (status.get("context") or {}).get("contracts") or {}
    council = contracts.get("council")
    if not isinstance(council, Mapping):
        return None
    modules = []
    for module in contracts.get("modules") or []:
        operations = [
            op
            for interface in module.get("provides") or []
            for op in interface.get("operations") or []
        ]
        modules.append(
            {
                "modul": module.get("module_id"),
                "krav": ", ".join(module.get("requirement_ids") or []),
                "interfaces": ", ".join(
                    str(i.get("interface")) for i in module.get("provides") or []
                ),
                "operationer": len(operations),
                "bruger": ", ".join(
                    f"{u.get('module_id')}.{u.get('interface')}"
                    for u in module.get("consumes") or []
                ),
                "ejer": ", ".join(module.get("owned_paths") or []),
            }
        )
    return {
        "status": council.get("status"),
        "rounds": len(council.get("rounds") or []),
        "roles": {
            role: f"{(identity or {}).get('brand')} · {(identity or {}).get('model')}"
            for role, identity in (council.get("roles") or {}).items()
        },
        "modules": modules,
        "criteria": len(contracts.get("acceptance_criteria") or []),
        "http_operations": sum(
            len(ops)
            for ops in ((contracts.get("openapi") or {}).get("paths") or {}).values()
        ),
        "build_layers": list(council.get("build_layers") or []),
        "open_findings": [
            {
                "kilde": item.get("source"),
                "alvor": item.get("severity"),
                "mål": item.get("target"),
                "fund": item.get("issue"),
            }
            for item in council.get("open_findings") or []
        ],
    }


def work_plan_summary(status: Mapping[str, Any]) -> dict[str, Any] | None:
    """The work plan (step 5), approved together with the contracts."""
    plan = (status.get("context") or {}).get("work_plan")
    if not isinstance(plan, Mapping):
        return None
    scaling = plan.get("scaling_plan") or {}
    return {
        "milestone": plan.get("milestone_id"),
        "fingerprint": str(plan.get("fingerprint") or "")[:12],
        "sprints": [
            {"sprint": s.get("sprint"), "pakker": ", ".join(s.get("packages") or [])}
            for s in plan.get("sprints") or []
        ],
        "packages": [
            {
                "pakke": p.get("logical_task_id"),
                "type": p.get("task_type"),
                "sprint": p.get("sprint"),
                "afhænger af": ", ".join(p.get("dependency_ids") or []),
                "skriver i": ", ".join(
                    (p.get("write_scope") or {}).get("allowed_paths") or []
                ),
                "kriterier": len(p.get("criterion_ids") or []),
                "vægt": p.get("weight"),
            }
            for p in plan.get("packages") or []
        ],
        "critical_path": list(plan.get("critical_path") or []),
        "critical_path_weight": scaling.get("critical_path_weight"),
        "total_weight": scaling.get("total_weight"),
        "agents_per_role": dict(scaling.get("parallel_agents_per_role") or {}),
        "status": scaling.get("status"),
    }


# --------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------- #
def render_factory_console(client: Any, organization_id: str | None) -> None:
    import streamlit as st

    st.header("Fabrik")
    st.caption(
        "Projektoverblik, godkendelsesindbakke og projektkonfiguration for pipelinen. "
        "Konsollen viser backendens tilstand og sender kommandoer; den beslutter intet."
    )
    if not organization_id:
        st.warning("Vælg eller opret en aktiv organisation ovenfor først.")
        return

    try:
        pipelines = list_pipelines(client, organization_id)
    except FactoryConsoleError as exc:
        st.error(str(exc))
        return

    overview_tab, inbox_tab, config_tab = st.tabs(
        ["📋 Projektoverblik", "📥 Godkendelsesindbakke", "⚙️ Projektkonfiguration"]
    )
    with inbox_tab:
        _render_inbox(st, client, organization_id, pipelines)
    with overview_tab:
        _render_overview(st, client, organization_id, pipelines)
    with config_tab:
        _render_configuration(st, client, organization_id, pipelines)


def _select_pipeline(st, pipelines: list[PipelineRow], key: str) -> PipelineRow | None:
    if not pipelines:
        st.info("Ingen pipelines endnu. Start en under Projektkonfiguration.")
        return None
    labels = [
        f"{row.project_name or row.name} · {row.state} · {row.workflow_id[:8]}"
        for row in pipelines
    ]
    index = st.selectbox(
        "Pipeline", range(len(pipelines)), format_func=labels.__getitem__, key=key
    )
    return pipelines[index]


def _render_overview(
    st, client, organization_id: str, pipelines: list[PipelineRow]
) -> None:
    st.subheader("Pipelines")
    st.dataframe(
        [
            {
                "projekt": row.project_name,
                "tilstand": row.state,
                "opdateret": row.updated_at,
                "id": row.workflow_id,
            }
            for row in pipelines
        ],
        hide_index=True,
        use_container_width=True,
    )
    row = _select_pipeline(st, pipelines, key="factory_overview_pipeline")
    if row is None:
        return
    try:
        status = pipeline_status(client, organization_id, row.workflow_id)
    except FactoryConsoleError as exc:
        st.error(str(exc))
        return

    left, middle, right = st.columns(3)
    left.metric("Tilstand", str(status.get("current_state")))
    summary = requirements_summary(status)
    middle.metric("Kravspec-revision", summary["revision"] if summary else "–")
    right.metric("Jobposter", len(status.get("jobs") or []))
    if status.get("error"):
        st.error(f"Pipeline-fejl: {status['error']}")

    council = council_summary(status)
    if council:
        _render_council(st, council)
    contract_council = contract_council_summary(status)
    if contract_council:
        _render_contract_council(st, contract_council)
    work_plan = work_plan_summary(status)
    if work_plan:
        _render_work_plan(st, work_plan)

    st.markdown("**Opgaver**")
    st.dataframe(status.get("tasks") or [], hide_index=True, use_container_width=True)
    st.markdown("**Jobposter**")
    jobs = job_rows(status)
    if jobs:
        st.dataframe(jobs, hide_index=True, use_container_width=True)
    else:
        st.caption("Ingen jobposter endnu.")
    st.markdown("**Artefakter og deres kravspec-revision**")
    provenance = provenance_rows(status)
    if provenance:
        st.dataframe(provenance, hide_index=True, use_container_width=True)
    else:
        st.caption("Ingen artefakter endnu.")


def _render_work_plan(st, plan: Mapping[str, Any]) -> None:
    st.markdown("**Arbejdsplan og skaleringsplan**")
    st.caption(
        f"Milestone {plan['milestone']} · {len(plan['sprints'])} dagssprint(s) · "
        f"fingeraftryk `{plan['fingerprint']}` · godkendes med kontrakterne ved "
        "kontrakt-gaten"
    )
    left, middle, right = st.columns(3)
    left.metric("Dagssprints", len(plan["sprints"]))
    middle.metric(
        "Kritisk vej (vægt)", f"{plan['critical_path_weight']} / {plan['total_weight']}"
    )
    right.metric("Kodere parallelt", plan["agents_per_role"].get("coder", "–"))
    st.dataframe(plan["sprints"], hide_index=True, use_container_width=True)
    st.dataframe(plan["packages"], hide_index=True, use_container_width=True)
    st.caption("Kritisk vej: " + " → ".join(plan["critical_path"]))


def _render_contract_council(st, council: Mapping[str, Any]) -> None:
    st.markdown("**Kontraktrådet**")
    roles = " · ".join(f"{role}: {who}" for role, who in council["roles"].items())
    if council["status"] == "agreed":
        st.success(
            f"Kontraktforfatter og kontekstkontrollant er enige efter "
            f"{council['rounds']} runde(r). {roles}"
        )
    else:
        st.warning(
            f"Uenighed om kontrakterne efter {council['rounds']} runde(r); afgøres af "
            f"dig ved kontrakt-gaten. {roles}"
        )
    if council["open_findings"]:
        st.dataframe(
            council["open_findings"], hide_index=True, use_container_width=True
        )
    st.dataframe(council["modules"], hide_index=True, use_container_width=True)
    st.caption(
        f"{council['criteria']} acceptkriterier · {council['http_operations']} "
        "HTTP-operationer i den afledte OpenAPI"
    )
    if council["build_layers"]:
        st.caption(
            "Byggerækkefølge: "
            + " → ".join(
                "[" + ", ".join(layer) + "]" for layer in council["build_layers"]
            )
        )


def _render_council(st, council: Mapping[str, Any]) -> None:
    st.markdown("**Arkitekturrådet**")
    roles = " · ".join(f"{role}: {who}" for role, who in council["roles"].items())
    if council["status"] == "agreed":
        st.success(
            f"Arkitekt og reviewer er enige efter {council['rounds']} runde(r). {roles}"
        )
    else:
        st.warning(
            f"Uenighed efter {council['rounds']} runde(r); afgøres af dig ved "
            f"arkitektur-gaten. {roles}"
        )
    if council["open_findings"]:
        st.dataframe(
            council["open_findings"], hide_index=True, use_container_width=True
        )
    stack = council["stack"]
    if stack:
        st.caption(
            f"Stak: {stack.get('language')} · {stack.get('framework')} · "
            f"{stack.get('persistence')}. {stack.get('rationale', '')}"
        )
    st.dataframe(council["modules"], hide_index=True, use_container_width=True)
    if council["build_layers"]:
        st.caption(
            "Kan bygges parallelt i lag: "
            + " → ".join(
                "[" + ", ".join(layer) + "]" for layer in council["build_layers"]
            )
        )


def _render_inbox(
    st, client, organization_id: str, pipelines: list[PipelineRow]
) -> None:
    gates: dict[str, list[dict[str, Any]]] = {}
    failures: list[str] = []
    for row in pipelines:
        try:
            gates[row.workflow_id] = pipeline_gates(
                client, organization_id, row.workflow_id
            )
        except FactoryConsoleError as exc:
            failures.append(f"{row.project_name}: {exc}")
    for failure in failures:
        st.error(failure)
    items = inbox_items(pipelines, gates)
    st.subheader(f"Venter på din beslutning ({len(items)})")
    if not items:
        st.success("Intet venter på en beslutning.")
        return
    for item in items:
        with st.container(border=True):
            st.markdown(
                f"**{item.gate_name}** · {item.project_name} · tilstand `{item.state}`"
            )
            if item.description:
                st.caption(item.description)
            approve_col, reject_col = st.columns(2)
            key = f"{item.workflow_id}_{item.gate_id}"
            if approve_col.button("✅ Godkend", key=f"factory_approve_{key}"):
                _decide(st, client, organization_id, item, approve=True)
            if reject_col.button("❌ Afvis", key=f"factory_reject_{key}"):
                _decide(st, client, organization_id, item, approve=False)


def _decide(
    st, client, organization_id: str, item: InboxItem, *, approve: bool
) -> None:
    try:
        decide_gate(
            client, organization_id, item.workflow_id, item.gate_id, approve=approve
        )
    except FactoryConsoleError as exc:
        st.error(str(exc))
        return
    st.success("Beslutningen er registreret af backend.")
    st.rerun()


def _render_configuration(
    st, client, organization_id: str, pipelines: list[PipelineRow]
) -> None:
    st.subheader("Start en pipeline fra en kravspec")
    uploaded = st.file_uploader(
        "Kravspec (YAML)", type=["yaml", "yml"], key="factory_kravspec_file"
    )
    text = st.text_area(
        "…eller indsæt kravspec",
        value=uploaded.getvalue().decode("utf-8") if uploaded is not None else "",
        height=200,
        key="factory_kravspec_text",
    )
    if st.button("Start pipeline", key="factory_start"):
        try:
            started = start_pipeline(client, organization_id, text)
        except FactoryConsoleError as exc:
            st.error(str(exc))
        else:
            st.success(f"Pipeline startet: {started['workflow_id']}")
            st.rerun()

    st.divider()
    st.subheader("Projektets kravspec")
    row = _select_pipeline(st, pipelines, key="factory_config_pipeline")
    if row is None:
        return
    try:
        status = pipeline_status(client, organization_id, row.workflow_id)
        yaml_text = requirements_yaml(client, organization_id, row.workflow_id)
    except FactoryConsoleError as exc:
        st.error(str(exc))
        return
    summary = requirements_summary(status)
    if summary:
        st.markdown(
            f"Gældende revision **{summary['revision']}** · erklæret version "
            f"`{summary['declared_version']}` · fingeraftryk `{summary['fingerprint']}` · "
            f"{len(summary['requirement_ids'])} krav"
        )
    else:
        st.warning("Pipelinen har ingen bundet kravspec-revision.")
    history = requirements_history(status)
    if history:
        st.markdown("**Tidligere revisioner**")
        st.dataframe(history, hide_index=True, use_container_width=True)
    with st.expander("Kravspec (YAML)"):
        st.code(yaml_text, language="yaml")
