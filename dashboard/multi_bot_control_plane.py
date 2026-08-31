"""Phase 9 Streamlit views for governed multi-bot configuration and evidence."""

from __future__ import annotations

import json
import os
from uuid import uuid4

import streamlit as st

from dashboard.control_plane_api import (
    CREATE_EXAMPLES,
    ControlPlaneAPI,
    ControlPlaneAPIError,
    resource_path,
)


def _client() -> ControlPlaneAPI | None:
    token = st.session_state.get("dor_api_token", os.getenv("DOR_API_TOKEN", ""))
    organization = st.session_state.get("dor_org_id", os.getenv("DOR_ORG_ID", ""))
    base = st.session_state.get(
        "dor_api_base", os.getenv("DOR_API_BASE", "http://localhost:8000")
    )
    with st.expander(
        "Control Plane-forbindelse", expanded=not bool(token and organization)
    ):
        base = st.text_input("API base URL", value=base, key="phase9_api_base")
        organization = st.text_input(
            "Organization ID", value=organization, key="phase9_org"
        )
        token = st.text_input(
            "Bearer token", value=token, type="password", key="phase9_token"
        )
        if st.button("Anvend forbindelse"):
            st.session_state["dor_api_base"] = base
            st.session_state["dor_org_id"] = organization
            st.session_state["dor_api_token"] = token
            st.rerun()
    try:
        return ControlPlaneAPI(base, token, organization)
    except ValueError as exc:
        st.info(str(exc))
        return None


def _table(client: ControlPlaneAPI, resource: str) -> None:
    try:
        rows = client.get(resource_path(resource))
    except ControlPlaneAPIError as exc:
        st.error(str(exc))
        return
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen poster i organisationens katalog.")


def _create_form(client: ControlPlaneAPI, resource: str) -> None:
    st.caption(
        "JSON følger den versionerede API-kontrakt. Secret-værdier må aldrig "
        "indsættes; brug kun en secret reference."
    )
    text = st.text_area(
        "Payload",
        json.dumps(CREATE_EXAMPLES[resource], indent=2),
        height=310,
        key=f"payload-{resource}",
    )
    if st.button(f"Opret {resource}", key=f"create-{resource}", type="primary"):
        try:
            payload = json.loads(text)
            payload["command_id"] = payload.get("command_id") or f"dashboard-{uuid4()}"
            result = client.post(resource_path(resource), payload)
            st.success(f"{resource.capitalize()} blev oprettet og auditeret.")
            st.json(result)
        except json.JSONDecodeError:
            st.error("Payload er ikke gyldig JSON.")
        except ControlPlaneAPIError as exc:
            st.error(str(exc))


def _catalog_tab(client: ControlPlaneAPI, resource: str) -> None:
    _table(client, resource)
    with st.expander(f"Opret {resource}"):
        _create_form(client, resource)
    if resource in {"connections", "deployments", "profiles"}:
        with st.expander(f"Deaktivér {resource}"):
            item_id = st.text_input("ID", key=f"disable-id-{resource}")
            if st.button("Deaktivér", key=f"disable-{resource}"):
                if not item_id.strip():
                    st.error("ID er påkrævet.")
                else:
                    singular = {
                        "connections": "connections",
                        "deployments": "deployments",
                        "profiles": "profiles",
                    }[resource]
                    try:
                        result = client.post(
                            f"{resource_path(resource)}/{item_id}/disable",
                            {"command_id": f"dashboard-disable-{uuid4()}"},
                        )
                        st.success(f"{singular.capitalize()} er deaktiveret.")
                        st.json(result)
                    except ControlPlaneAPIError as exc:
                        st.error(str(exc))


def _allocation_tab(client: ControlPlaneAPI) -> None:
    st.markdown(
        "Allokér selv botprofiler til roller. Systemet vælger kun blandt "
        "medlemmerne i den godkendte pool; ingen AI-brand er hardcoded til en rolle."
    )
    allocation_id = st.text_input("Allocation ID", "architecture-review-pool")
    with st.expander("Hent eksisterende allokering"):
        if st.button("Hent allokering"):
            try:
                st.json(
                    client.get(f"/api/v1/bot-governance/allocations/{allocation_id}")
                )
            except ControlPlaneAPIError as exc:
                st.error(str(exc))
    example = {
        "command_id": "configure-allocation-001",
        "allocation_id": allocation_id,
        "role_id": "chief-architect",
        "role_version": 1,
        "members": [
            {
                "bot_profile_id": "architect-mistral-1",
                "bot_profile_version": 1,
                "preference_rank": 1,
                "fallback_rank": None,
            }
        ],
        "independence_level": "provider",
        "autonomy_level": 2,
        "hard_constraints": {},
        "approved_by": "controller",
        "enabled": True,
    }
    text = st.text_area("Allocation payload", json.dumps(example, indent=2), height=330)
    if st.button("Opret allokeringspool", type="primary"):
        try:
            st.json(client.post("/api/v1/bot-governance/allocations", json.loads(text)))
        except (json.JSONDecodeError, ControlPlaneAPIError) as exc:
            st.error(str(exc))


def _selection_tab(client: ControlPlaneAPI) -> None:
    st.markdown(
        "Selection fryser konkrete bot-, deployment- og connection-versioner "
        "for et run. Det gør efterfølgende replay og audit deterministisk."
    )
    run_id = st.text_input("Run ID", "run-001")
    if st.button("Hent selection decision"):
        try:
            result = client.get(f"/api/v1/bot-selections/{run_id}")
            st.json(result)
        except ControlPlaneAPIError as exc:
            st.error(str(exc))
    with st.expander("Opret og frys selection"):
        zero64 = "0" * 64
        payload = {
            "command_id": "select-bots-001",
            "run_id": run_id,
            "template_id": "architecture-council",
            "template_version": 1,
            "allocation_refs": [["architecture-review-pool", 1]],
            "scope_id": "project-001",
            "repository": "owner/repository",
            "base_sha": "0" * 40,
            "requirements_fingerprint": zero64,
            "architecture_fingerprint": zero64,
            "contract_fingerprint": zero64,
            "input_fingerprint": zero64,
        }
        text = st.text_area(
            "Selection payload", json.dumps(payload, indent=2), height=390
        )
        if st.button("Vælg og frys bots", type="primary"):
            try:
                st.json(client.post("/api/v1/bot-selections", json.loads(text)))
            except (json.JSONDecodeError, ControlPlaneAPIError) as exc:
                st.error(str(exc))


def _evidence_tab() -> None:
    st.warning(
        "Evaluation/performance og factory-work er implementeret som durable "
        "domæne-/persistencelag, men er endnu ikke eksponeret gennem den "
        "kanoniske HTTP API. GUI'en viser derfor ikke mock-evidens. Fase 10 skal "
        "åbne read-only, tenant-scopede endpoints før data kan vises her."
    )
    st.table(
        [
            {
                "område": "Evaluation records og snapshots",
                "HTTP-kontrakt": "mangler",
                "UI": "blokeret fail-closed",
            },
            {
                "område": "Work packages og candidates",
                "HTTP-kontrakt": "mangler",
                "UI": "blokeret fail-closed",
            },
            {
                "område": "Integration receipts",
                "HTTP-kontrakt": "mangler",
                "UI": "blokeret fail-closed",
            },
        ]
    )


def render_multi_bot_control_plane() -> None:
    st.header("🧠 Multi-bot Control Plane")
    st.caption(
        "Konfigurér providers, flere bots pr. brand, roller og godkendte pools "
        "uden hardcoded brand→rolle-bindinger."
    )
    client = _client()
    if client is None:
        return
    tabs = st.tabs(
        [
            "Forbindelser",
            "Deployments",
            "Botprofiler",
            "Roller",
            "Council templates",
            "Allokering",
            "Selection",
            "Evidens",
        ]
    )
    for tab, resource in zip(
        tabs[:5],
        ("connections", "deployments", "profiles", "roles", "templates"),
        strict=True,
    ):
        with tab:
            _catalog_tab(client, resource)
    with tabs[5]:
        _allocation_tab(client)
    with tabs[6]:
        _selection_tab(client)
    with tabs[7]:
        _evidence_tab()
