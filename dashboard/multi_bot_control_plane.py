"""Governed multi-bot administration inside the canonical Streamlit control plane."""

from __future__ import annotations

import json
from uuid import uuid4

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.control_plane_api import CREATE_EXAMPLES, resource_path


def _org_params(organization_id: str) -> dict[str, str]:
    return {"organization_id": organization_id}


def _get(client: DORAPIClient, organization_id: str, path: str):
    return client.get(path, params=_org_params(organization_id))


def _post(
    client: DORAPIClient,
    organization_id: str,
    path: str,
    payload: dict,
):
    return client.post(path, params=_org_params(organization_id), json=payload)


def _table(client: DORAPIClient, organization_id: str, resource: str) -> None:
    try:
        rows = _get(client, organization_id, resource_path(resource))
    except DORAPIError as exc:
        st.error(f"API-fejl ({exc.status_code}): {exc}")
        return
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("Ingen poster i organisationens katalog.")


def _create_form(
    client: DORAPIClient, organization_id: str, resource: str
) -> None:
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
            result = _post(client, organization_id, resource_path(resource), payload)
            st.success(f"{resource.capitalize()} blev oprettet og auditeret.")
            st.json(result)
        except json.JSONDecodeError:
            st.error("Payload er ikke gyldig JSON.")
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")


def _catalog_tab(
    client: DORAPIClient, organization_id: str, resource: str
) -> None:
    _table(client, organization_id, resource)
    with st.expander(f"Opret {resource}"):
        _create_form(client, organization_id, resource)
    if resource in {"connections", "deployments", "profiles"}:
        with st.expander(f"Deaktivér {resource}"):
            item_id = st.text_input("ID", key=f"disable-id-{resource}")
            if st.button("Deaktivér", key=f"disable-{resource}"):
                if not item_id.strip():
                    st.error("ID er påkrævet.")
                    return
                try:
                    result = _post(
                        client,
                        organization_id,
                        f"{resource_path(resource)}/{item_id.strip()}/disable",
                        {"command_id": f"dashboard-disable-{uuid4()}"},
                    )
                    st.success(f"{resource.capitalize()} er deaktiveret.")
                    st.json(result)
                except DORAPIError as exc:
                    st.error(f"API-fejl ({exc.status_code}): {exc}")


def _allocation_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown(
        "Allokér botprofiler til roller. Systemet vælger kun blandt medlemmerne "
        "i den godkendte pool; ingen AI-brand er hardcoded til en rolle."
    )
    allocation_id = st.text_input("Allocation ID", "architecture-review-pool")
    with st.expander("Hent eksisterende allokering"):
        if st.button("Hent allokering"):
            try:
                st.json(
                    _get(
                        client,
                        organization_id,
                        f"/api/v1/bot-governance/allocations/{allocation_id}",
                    )
                )
            except DORAPIError as exc:
                st.error(f"API-fejl ({exc.status_code}): {exc}")
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
    text = st.text_area(
        "Allocation payload", json.dumps(example, indent=2), height=330
    )
    if st.button("Opret allokeringspool", type="primary"):
        try:
            st.json(
                _post(
                    client,
                    organization_id,
                    "/api/v1/bot-governance/allocations",
                    json.loads(text),
                )
            )
        except json.JSONDecodeError:
            st.error("Payload er ikke gyldig JSON.")
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")


def _selection_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown(
        "Selection fryser konkrete bot-, deployment- og connection-versioner "
        "for et run, så replay og audit er deterministisk."
    )
    run_id = st.text_input("Run ID", "run-001")
    if st.button("Hent selection decision"):
        try:
            st.json(_get(client, organization_id, f"/api/v1/bot-selections/{run_id}"))
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")
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
                st.json(
                    _post(
                        client,
                        organization_id,
                        "/api/v1/bot-selections",
                        json.loads(text),
                    )
                )
            except json.JSONDecodeError:
                st.error("Payload er ikke gyldig JSON.")
            except DORAPIError as exc:
                st.error(f"API-fejl ({exc.status_code}): {exc}")


def _evidence_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown(
        "Læs immutable, tenant-scoped evidens direkte fra de durable stores. "
        "Fanen kan ikke ændre historik eller resultater."
    )
    evidence_type = st.selectbox(
        "Evidenstype",
        [
            "evaluations",
            "observations",
            "snapshots",
            "work-packages",
            "candidates",
            "candidate-selections",
            "integration-plans",
            "integration-receipts",
        ],
    )
    identity = st.text_input("Evidence ID eller plan fingerprint")
    if st.button("Hent verificeret evidens"):
        if not identity.strip():
            st.error("Evidence ID er påkrævet.")
            return
        try:
            evidence = _get(
                client,
                organization_id,
                f"/api/v1/bot-evidence/{evidence_type}/{identity.strip()}",
            )
            st.success(
                f"{evidence['evidence_type']} · fingerprint {evidence['fingerprint']}"
            )
            st.json(evidence["payload"])
        except DORAPIError as exc:
            st.error(f"API-fejl ({exc.status_code}): {exc}")


def render_multi_bot_control_plane(
    client: DORAPIClient, organization_id: str
) -> None:
    """Render live bot governance using the canonical authenticated GUI client."""
    if not organization_id.strip():
        st.warning("Angiv organisation ID for at administrere bot governance.")
        return

    organization_id = organization_id.strip()
    st.subheader("🧠 Bot Governance & Multi-bot Control Plane")
    st.caption(
        "Live tenant-scoped administration via samme authenticated API-session som "
        "resten af Control Plane GUI'en. Ingen separat token- eller base-URL-konfiguration."
    )
    st.info(
        "Append-only governance: ingen DELETE. Disable registreres kun som eksplicit "
        "backend-handling."
    )

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
            _catalog_tab(client, organization_id, resource)
    with tabs[5]:
        _allocation_tab(client, organization_id)
    with tabs[6]:
        _selection_tab(client, organization_id)
    with tabs[7]:
        _evidence_tab(client, organization_id)
