"""Human-facing governed AI-bot administration for the Operator GUI."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.governance_catalog import resource_path

PROTOCOL_FUNCTIONS = (
    "conversation_owner",
    "proposer",
    "reviewer",
    "verifier",
    "implementer",
    "candidate_evaluator",
    "integrator",
)
INDEPENDENCE_LEVELS = (
    "profile",
    "connection",
    "model_family",
    "provider",
    "brand",
    "deployment",
)
PROVIDER_PRESETS = {
    "OpenAI": ("openai", "https://api.openai.com/v1"),
    "Anthropic": ("anthropic", "https://api.anthropic.com"),
    "Mistral": ("mistral", "https://api.mistral.ai/v1"),
    "OpenAI-kompatibel": ("openai_compatible", ""),
    "Lokal / anden": ("custom", ""),
}
DATA_BOUNDARIES = ("eu", "organization", "global", "local")


def _org_params(organization_id: str) -> dict[str, str]:
    return {"organization_id": organization_id}


def _get(client: DORAPIClient, organization_id: str, path: str):
    return client.get(path, params=_org_params(organization_id))


def _post(
    client: DORAPIClient,
    organization_id: str,
    path: str,
    payload: dict[str, Any],
):
    return client.post(path, params=_org_params(organization_id), json=payload)


def _put(client: DORAPIClient, path: str, payload: dict[str, Any]):
    return client.put(path, json=payload)


def _rows(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def _human_error(exc: DORAPIError, action: str) -> str:
    if exc.status_code == 401:
        return "Din session er udløbet. Log ind igen."
    if exc.status_code == 403:
        return (
            f"DOR afviste at {action}. Din organisation eller runtime-authority "
            "tillader ikke handlingen."
        )
    if exc.status_code == 409:
        return f"DOR kunne ikke {action}, fordi kataloget er ændret. Hent siden igen."
    if exc.status_code == 422:
        return f"DOR kunne ikke {action}. Kontrollér felterne og prøv igen."
    return f"DOR kunne ikke {action} (fejlkode {exc.status_code})."


def build_connection_payload(
    *,
    connection_id: str,
    brand: str,
    adapter_type: str,
    endpoint: str,
    secret_reference: str,
    region: str | None = None,
    data_boundary: str = "global",
    concurrency_limit: int = 1,
) -> dict[str, Any]:
    return {
        "command_id": f"dashboard-connection-{uuid4()}",
        "connection_id": connection_id.strip(),
        "brand": brand.strip(),
        "adapter_type": adapter_type.strip(),
        "endpoint": endpoint.strip(),
        "secret_reference": secret_reference.strip(),
        "region": (region or "").strip() or None,
        "data_boundary": data_boundary,
        "concurrency_limit": int(concurrency_limit),
        "enabled": True,
    }


def build_deployment_payload(
    *,
    deployment_id: str,
    connection_id: str,
    connection_version: int,
    model_id: str,
    model_family: str,
    max_context_tokens: int,
    max_output_tokens: int,
    structured_output: bool,
    tool_capabilities: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "command_id": f"dashboard-deployment-{uuid4()}",
        "deployment_id": deployment_id.strip(),
        "connection_id": connection_id.strip(),
        "connection_version": int(connection_version),
        "model_id": model_id.strip(),
        "model_family": model_family.strip(),
        "max_context_tokens": int(max_context_tokens),
        "max_output_tokens": int(max_output_tokens),
        "structured_output": bool(structured_output),
        "tool_capabilities": sorted(
            {value.strip() for value in (tool_capabilities or []) if value.strip()}
        ),
    }


def build_profile_payload(
    *,
    bot_profile_id: str,
    agent_identity: str,
    display_name: str,
    deployment_id: str,
    deployment_revision: int,
    prompt_version: str,
    capabilities: list[str],
    permitted_tools: list[str] | None = None,
    data_boundary: str = "global",
    source_code_allowed: bool = True,
    max_cost_minor_units: int | None = None,
    max_input_tokens: int = 32_000,
    max_output_tokens: int = 4_096,
    concurrency_limit: int = 1,
    enabled: bool = False,
) -> dict[str, Any]:
    return {
        "command_id": f"dashboard-profile-{uuid4()}",
        "bot_profile_id": bot_profile_id.strip(),
        "agent_identity": agent_identity.strip(),
        "display_name": display_name.strip(),
        "deployment_id": deployment_id.strip(),
        "deployment_revision": int(deployment_revision),
        "prompt_version": prompt_version.strip(),
        "capabilities": sorted({value.strip() for value in capabilities if value.strip()}),
        "permitted_tools": sorted(
            {value.strip() for value in (permitted_tools or []) if value.strip()}
        ),
        "data_policy": {
            "boundary": data_boundary.strip() or "global",
            "allowed_regions": [],
            "source_code_allowed": bool(source_code_allowed),
        },
        "budget_policy": {
            "max_cost_minor_units": max_cost_minor_units,
            "max_input_tokens": int(max_input_tokens),
            "max_output_tokens": int(max_output_tokens),
        },
        "concurrency_limit": int(concurrency_limit),
        "enabled": bool(enabled),
    }


def build_role_payload(
    *,
    role_id: str,
    name: str,
    purpose: str,
    protocol_function: str,
    required_capabilities: list[str],
    output_schema_ref: str,
    rubric_ref: str,
    input_schema_ref: str | None = None,
    independent_verification: bool = True,
) -> dict[str, Any]:
    return {
        "command_id": f"dashboard-role-{uuid4()}",
        "role_id": role_id.strip(),
        "name": name.strip(),
        "purpose": purpose.strip(),
        "protocol_function": protocol_function,
        "required_capabilities": sorted(
            {value.strip() for value in required_capabilities if value.strip()}
        ),
        "output_schema_ref": output_schema_ref.strip(),
        "rubric_ref": rubric_ref.strip(),
        "input_schema_ref": (input_schema_ref or "").strip() or None,
        "independent_verification": bool(independent_verification),
        "enabled": True,
    }


def build_allocation_payload(
    *,
    allocation_id: str,
    role_id: str,
    role_version: int,
    primary_profile_id: str,
    primary_profile_version: int,
    fallback_profile_id: str | None = None,
    fallback_profile_version: int | None = None,
    independence_level: str = "provider",
    autonomy_level: int = 2,
    approved_by: str = "operator-admin",
) -> dict[str, Any]:
    members = [
        {
            "bot_profile_id": primary_profile_id.strip(),
            "bot_profile_version": int(primary_profile_version),
            "preference_rank": 1,
            "fallback_rank": None,
        }
    ]
    fallback = (fallback_profile_id or "").strip()
    if fallback:
        members.append(
            {
                "bot_profile_id": fallback,
                "bot_profile_version": int(fallback_profile_version or 1),
                "preference_rank": 2,
                "fallback_rank": 1,
            }
        )
    return {
        "command_id": f"dashboard-allocation-{uuid4()}",
        "allocation_id": allocation_id.strip(),
        "role_id": role_id.strip(),
        "role_version": int(role_version),
        "members": members,
        "independence_level": independence_level,
        "autonomy_level": int(autonomy_level),
        "hard_constraints": {},
        "approved_by": approved_by.strip() or "operator-admin",
        "enabled": True,
    }


def _load_catalog(
    client: DORAPIClient, organization_id: str, resource: str
) -> list[dict[str, Any]] | None:
    try:
        return _rows(_get(client, organization_id, resource_path(resource)))
    except DORAPIError as exc:
        st.error(_human_error(exc, f"hente {resource}"))
    except Exception:
        st.error("Status kan ikke fastslås")
    return None


def _render_table(rows: list[dict[str, Any]], *, empty: str) -> None:
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info(empty)


def _credential_path(organization_id: str, connection_id: str) -> str:
    return (
        f"/api/v1/control-plane/organizations/{organization_id}/"
        f"bot-provider-credentials/{connection_id}"
    )


def _connection_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown("### AI-forbindelser")
    st.caption(
        "Tilføj en provider og API-nøgle én gang. Nøglen krypteres af backenden "
        "og bliver aldrig vist igen."
    )
    connections = _load_catalog(client, organization_id, "connections")
    if connections is None:
        return
    _render_table(
        [
            {
                "Navn / ID": row.get("connection_id"),
                "Provider": row.get("brand"),
                "Endpoint": row.get("endpoint"),
                "Region": row.get("region") or "—",
                "Aktiv": "Ja" if row.get("enabled") else "Nej",
                "Version": row.get("version"),
            }
            for row in connections
        ],
        empty="Der er ingen AI-forbindelser endnu.",
    )

    with st.expander("Tilføj AI-forbindelse", expanded=not connections):
        with st.form("create-ai-connection"):
            connection_id = st.text_input(
                "Forbindelses-ID", placeholder="openai-production"
            )
            provider = st.selectbox("Udbyder", list(PROVIDER_PRESETS))
            preset_adapter, preset_endpoint = PROVIDER_PRESETS[provider]
            endpoint = st.text_input(
                "API endpoint",
                value=preset_endpoint,
                placeholder="https://provider.example/v1",
            )
            api_key = st.text_input(
                "API-nøgle",
                type="password",
                help="Gemmes krypteret i DOR. Den eksisterende nøgle kan ikke læses tilbage.",
            )
            region = st.text_input("Region", placeholder="eu-west")
            data_boundary = st.selectbox("Dataområde", DATA_BOUNDARIES)
            concurrency = st.number_input(
                "Maks. samtidige kald", min_value=1, value=1
            )
            if provider in {"OpenAI-kompatibel", "Lokal / anden"}:
                adapter_type = st.text_input(
                    "Adaptertype",
                    value=preset_adapter,
                    help="Canonical adapter-id for den valgte provider.",
                )
            else:
                adapter_type = preset_adapter
            submitted = st.form_submit_button("Gem forbindelse", type="primary")

        if submitted:
            clean_id = connection_id.strip()
            if not clean_id or not endpoint.strip() or not api_key.strip():
                st.error("Forbindelses-ID, API endpoint og API-nøgle er påkrævet.")
            else:
                try:
                    credential = _put(
                        client,
                        _credential_path(organization_id, clean_id),
                        {"api_key": api_key},
                    )
                    if not isinstance(credential, Mapping):
                        raise ValueError("credential status is malformed")
                    reference = credential.get("secret_reference")
                    if credential.get("credential_configured") is not True or not isinstance(
                        reference, str
                    ) or not reference.strip():
                        raise ValueError("credential was not confirmed")
                    payload = build_connection_payload(
                        connection_id=clean_id,
                        brand=provider,
                        adapter_type=adapter_type,
                        endpoint=endpoint,
                        secret_reference=reference,
                        region=region,
                        data_boundary=data_boundary,
                        concurrency_limit=int(concurrency),
                    )
                    _post(
                        client,
                        organization_id,
                        resource_path("connections"),
                        payload,
                    )
                except DORAPIError as exc:
                    st.error(_human_error(exc, "gemme AI-forbindelsen"))
                except Exception:
                    st.error("Status kan ikke fastslås")
                else:
                    st.success(
                        "AI-forbindelsen er gemt. API-nøglen er krypteret og skjult."
                    )
                    st.rerun()

    enabled = [row for row in connections if row.get("enabled") is True]
    if enabled:
        with st.expander("Deaktivér forbindelse"):
            labels = {
                f"{row.get('connection_id')} · {row.get('brand')}": row
                for row in enabled
                if row.get("connection_id")
            }
            selected = st.selectbox(
                "Forbindelse", list(labels), key="disable-connection"
            )
            if st.button("Deaktivér forbindelse", key="disable-connection-submit"):
                connection = labels[selected]
                try:
                    _post(
                        client,
                        organization_id,
                        f"{resource_path('connections')}/{connection['connection_id']}/disable",
                        {"command_id": f"dashboard-disable-{uuid4()}"},
                    )
                except DORAPIError as exc:
                    st.error(_human_error(exc, "deaktivere forbindelsen"))
                else:
                    st.success("Forbindelsen er deaktiveret af backenden.")
                    st.rerun()


def _deployment_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown("### Modeller")
    connections = _load_catalog(client, organization_id, "connections")
    deployments = _load_catalog(client, organization_id, "deployments")
    if connections is None or deployments is None:
        return
    _render_table(
        [
            {
                "Model": row.get("model_id"),
                "Deployment": row.get("deployment_id"),
                "Forbindelse": row.get("connection_id"),
                "Status": row.get("status"),
                "Revision": row.get("revision"),
            }
            for row in deployments
        ],
        empty="Der er ingen modeller registreret endnu.",
    )
    active = [
        row
        for row in connections
        if row.get("enabled") is True and row.get("connection_id") and row.get("version")
    ]
    if not active:
        st.info("Opret eller aktivér først en AI-forbindelse.")
        return
    labels = {
        f"{row['connection_id']} · {row.get('brand') or 'provider'}": row for row in active
    }
    with st.expander("Tilføj model", expanded=not deployments):
        with st.form("create-model-deployment"):
            deployment_id = st.text_input("Deployment ID", placeholder="gpt-production")
            selected = st.selectbox("Forbindelse", list(labels))
            model_id = st.text_input("Model", placeholder="gpt-5.6")
            model_family = st.text_input("Modelfamilie", placeholder="gpt-5")
            context_tokens = st.number_input(
                "Maks. context tokens", min_value=1, value=128000, step=1000
            )
            output_tokens = st.number_input(
                "Maks. output tokens", min_value=1, value=8192, step=256
            )
            structured_output = st.checkbox("Structured output", value=True)
            tool_text = st.text_input("Tool capabilities")
            submitted = st.form_submit_button("Gem model", type="primary")
        if submitted:
            connection = labels[selected]
            try:
                _post(
                    client,
                    organization_id,
                    resource_path("deployments"),
                    build_deployment_payload(
                        deployment_id=deployment_id,
                        connection_id=str(connection["connection_id"]),
                        connection_version=int(connection["version"]),
                        model_id=model_id,
                        model_family=model_family,
                        max_context_tokens=int(context_tokens),
                        max_output_tokens=int(output_tokens),
                        structured_output=structured_output,
                        tool_capabilities=tool_text.split(","),
                    ),
                )
            except DORAPIError as exc:
                st.error(_human_error(exc, "gemme modellen"))
            else:
                st.success("Modellen er gemt i DORs bot-katalog.")
                st.rerun()


def _profile_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown("### AI-bots")
    deployments = _load_catalog(client, organization_id, "deployments")
    profiles = _load_catalog(client, organization_id, "profiles")
    if deployments is None or profiles is None:
        return
    _render_table(
        [
            {
                "Bot": row.get("display_name") or row.get("bot_profile_id"),
                "ID": row.get("bot_profile_id"),
                "Deployment": row.get("deployment_id"),
                "Capabilities": ", ".join(row.get("capabilities") or []),
                "Aktiv": "Ja" if row.get("enabled") else "Nej",
                "Version": row.get("version"),
            }
            for row in profiles
        ],
        empty="Der er ingen AI-bots endnu.",
    )
    active = [
        row
        for row in deployments
        if row.get("status") == "active"
        and row.get("deployment_id")
        and row.get("revision")
    ]
    if not active:
        st.info("Registrér først en aktiv model.")
        return
    labels = {
        f"{row['deployment_id']} · {row.get('model_id') or 'model'}": row
        for row in active
    }
    with st.expander("Tilføj AI-bot"):
        with st.form("create-bot-profile"):
            display_name = st.text_input("Botnavn", placeholder="Arkitekt")
            bot_profile_id = st.text_input("Bot ID", placeholder="architecture-primary")
            selected = st.selectbox("Model", list(labels))
            capabilities_text = st.text_input(
                "Capabilities", placeholder="architecture.propose, architecture.review"
            )
            prompt_version = st.text_input("Prompt-version", value="v1")
            concurrency = st.number_input("Samtidige opgaver", min_value=1, value=1)
            enabled = st.checkbox("Aktivér bot med det samme", value=False)
            with st.expander("Avanceret"):
                agent_identity = st.text_input(
                    "AI-1 agent identity",
                    help="SHA-256 identity, som allerede er registreret i DOR.",
                )
                data_boundary = st.selectbox(
                    "Bot-dataområde", DATA_BOUNDARIES, index=2
                )
                source_code_allowed = st.checkbox("Kildekode må sendes", value=True)
                max_input = st.number_input(
                    "Maks. input tokens", min_value=1, value=32000, step=1000
                )
                max_output = st.number_input(
                    "Maks. output tokens", min_value=1, value=4096, step=256
                )
            submitted = st.form_submit_button("Gem AI-bot", type="primary")
        if submitted:
            deployment = labels[selected]
            try:
                _post(
                    client,
                    organization_id,
                    resource_path("profiles"),
                    build_profile_payload(
                        bot_profile_id=bot_profile_id,
                        agent_identity=agent_identity,
                        display_name=display_name,
                        deployment_id=str(deployment["deployment_id"]),
                        deployment_revision=int(deployment["revision"]),
                        prompt_version=prompt_version,
                        capabilities=capabilities_text.split(","),
                        data_boundary=data_boundary,
                        source_code_allowed=source_code_allowed,
                        max_input_tokens=int(max_input),
                        max_output_tokens=int(max_output),
                        concurrency_limit=int(concurrency),
                        enabled=enabled,
                    ),
                )
            except DORAPIError as exc:
                st.error(_human_error(exc, "gemme AI-botten"))
            else:
                st.success("AI-botten er gemt i DORs bot-katalog.")
                st.rerun()


def _role_tab(client: DORAPIClient, organization_id: str) -> None:
    st.markdown("### Roller & tildeling")
    roles = _load_catalog(client, organization_id, "roles")
    profiles = _load_catalog(client, organization_id, "profiles")
    if roles is None or profiles is None:
        return
    _render_table(
        [
            {
                "Rolle": row.get("name") or row.get("role_id"),
                "Funktion": row.get("protocol_function"),
                "Capabilities": ", ".join(row.get("required_capabilities") or []),
                "Version": row.get("version"),
            }
            for row in roles
        ],
        empty="Der er ingen roller endnu.",
    )
    with st.expander("Opret rolle"):
        with st.form("create-bot-role"):
            name = st.text_input("Rollenavn", placeholder="Chief Architect")
            role_id = st.text_input("Rolle ID", placeholder="chief-architect")
            purpose = st.text_area("Formål")
            protocol_function = st.selectbox("Protocol function", PROTOCOL_FUNCTIONS)
            capabilities = st.text_input("Påkrævede capabilities")
            output_schema_ref = st.text_input(
                "Output schema", value="schema://generic/output/v1"
            )
            rubric_ref = st.text_input("Rubric", value="rubric://generic/v1")
            independent = st.checkbox("Kræv uafhængig verifikation", value=True)
            submitted = st.form_submit_button("Gem rolle", type="primary")
        if submitted:
            try:
                _post(
                    client,
                    organization_id,
                    resource_path("roles"),
                    build_role_payload(
                        role_id=role_id,
                        name=name,
                        purpose=purpose,
                        protocol_function=protocol_function,
                        required_capabilities=capabilities.split(","),
                        output_schema_ref=output_schema_ref,
                        rubric_ref=rubric_ref,
                        independent_verification=independent,
                    ),
                )
            except DORAPIError as exc:
                st.error(_human_error(exc, "gemme rollen"))
            else:
                st.success("Rollen er gemt i DOR.")
                st.rerun()

    active_roles = [
        row for row in roles
        if row.get("enabled") is True and row.get("role_id") and row.get("version")
    ]
    active_profiles = [
        row for row in profiles
        if row.get("enabled") is True and row.get("bot_profile_id") and row.get("version")
    ]
    if not active_roles or not active_profiles:
        st.info("Der skal være mindst én aktiv rolle og én aktiv AI-bot før tildeling.")
        return
    role_labels = {
        f"{row.get('name') or row['role_id']} · v{row['version']}": row
        for row in active_roles
    }
    profile_labels = {
        f"{row.get('display_name') or row['bot_profile_id']} · v{row['version']}": row
        for row in active_profiles
    }
    fallback_options = ["Ingen"] + list(profile_labels)
    st.markdown("#### Tildel bots til rolle")
    with st.form("create-role-allocation"):
        role_label = st.selectbox("Rolle", list(role_labels))
        primary_label = st.selectbox("Primær AI-bot", list(profile_labels))
        fallback_label = st.selectbox("Fallback AI-bot", fallback_options)
        allocation_id = st.text_input("Tildelings-ID", placeholder="chief-architect-production")
        independence = st.selectbox("Uafhængighedskrav", INDEPENDENCE_LEVELS, index=3)
        autonomy = st.slider("Autonominiveau", min_value=0, max_value=5, value=2)
        approved_by = st.text_input(
            "Godkendt af", value=str(st.session_state.get("username") or "operator-admin")
        )
        submitted = st.form_submit_button("Gem tildeling", type="primary")
    if submitted:
        role = role_labels[role_label]
        primary = profile_labels[primary_label]
        fallback = profile_labels.get(fallback_label)
        try:
            _post(
                client,
                organization_id,
                "/api/v1/bot-governance/allocations",
                build_allocation_payload(
                    allocation_id=allocation_id,
                    role_id=str(role["role_id"]),
                    role_version=int(role["version"]),
                    primary_profile_id=str(primary["bot_profile_id"]),
                    primary_profile_version=int(primary["version"]),
                    fallback_profile_id=(
                        str(fallback["bot_profile_id"]) if fallback else None
                    ),
                    fallback_profile_version=(
                        int(fallback["version"]) if fallback else None
                    ),
                    independence_level=independence,
                    autonomy_level=autonomy,
                    approved_by=approved_by,
                ),
            )
        except DORAPIError as exc:
            st.error(_human_error(exc, "gemme tildelingen"))
        else:
            st.success("Rolle-tildelingen er gemt og versioneret af backenden.")
            st.rerun()


def _advanced_tab(client: DORAPIClient, organization_id: str) -> None:
    st.subheader("🧠 Bot Governance & Multi-bot Control Plane")
    st.markdown("### Avanceret")
    st.caption(
        "Tekniske runtime- og evidensopslag. Der skal ikke skrives JSON eller API-payloads her."
    )
    templates = _load_catalog(client, organization_id, "templates")
    if templates is not None:
        with st.expander("Council templates"):
            _render_table(templates, empty="Ingen council templates.")
    with st.expander("Selection decision"):
        run_id = st.text_input("Run ID", key="selection-run-id")
        if st.button("Hent selection", key="selection-fetch") and run_id.strip():
            try:
                st.json(_get(client, organization_id, f"/api/v1/bot-selections/{run_id.strip()}"))
            except DORAPIError as exc:
                st.error(_human_error(exc, "hente selection"))


def render_multi_bot_control_plane(
    client: DORAPIClient, organization_id: str
) -> None:
    """Render governed bot administration using the canonical authenticated client."""
    if not organization_id.strip():
        st.warning("Vælg en organisation for at administrere AI-bots.")
        return
    organization_id = organization_id.strip()
    st.subheader("AI-bots")
    st.caption(
        "Opsæt provider/API-nøgle, model og bot; opret roller og vælg primær/fallback. "
        "DORs backend forbliver autoritativ for tenant-scope, credentials og rettigheder."
    )
    tabs = st.tabs(
        ["Forbindelser", "Modeller", "AI-bots", "Roller & tildeling", "Avanceret"]
    )
    with tabs[0]:
        _connection_tab(client, organization_id)
    with tabs[1]:
        _deployment_tab(client, organization_id)
    with tabs[2]:
        _profile_tab(client, organization_id)
    with tabs[3]:
        _role_tab(client, organization_id)
    with tabs[4]:
        _advanced_tab(client, organization_id)
