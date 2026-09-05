"""Governed onboarding entrypoint for the Streamlit Control Plane."""
from __future__ import annotations

import uuid
from typing import Any

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from generation.project_spec import ArchitectureKind, ProjectDefinition, SUPPORTED_STACKS
from phase4.onboarding import OnboardingPurpose


_PURPOSE_LABELS = {
    OnboardingPurpose.EXTEND.value: "Extend — forstå og udvid eksisterende løsning",
    OnboardingPurpose.MODERNIZE_REWRITE.value: "Modernize/rewrite — bevar adfærd på ny target stack",
    OnboardingPurpose.AUDIT_ONLY.value: "Audit only — vurder uden implementering",
}


def build_onboarding_payload(
    *,
    command_id: str,
    source_repository: str,
    purpose: str,
    rationale: str,
    supersedes_intent_id: str | None = None,
    target_name: str | None = None,
    target_architecture: str = "hexagonal",
    target_language: str = "python",
    target_api: str = "fastapi",
    target_database: str = "postgresql",
) -> dict[str, Any]:
    declared_purpose = OnboardingPurpose(purpose)
    target_stack: dict[str, Any] | None = None
    if declared_purpose is OnboardingPurpose.MODERNIZE_REWRITE:
        if not target_name:
            raise ValueError("Target project name er påkrævet for modernize/rewrite")
        target_stack = ProjectDefinition(
            name=target_name,
            architecture=target_architecture,
            language=target_language,
            api=target_api,
            database=target_database,
        ).model_dump(mode="json")
    elif target_name is not None:
        raise ValueError("Target stack er kun tilladt for modernize/rewrite")

    return {
        "command_id": command_id,
        "source_repository": source_repository,
        "purpose": declared_purpose.value,
        "rationale": rationale,
        "target_stack": target_stack,
        "supersedes_intent_id": supersedes_intent_id or None,
    }


def render_onboarding(client: DORAPIClient) -> None:
    st.subheader("Repository onboarding")
    st.write(
        "Vælg formålet **før** audit. Valget registreres immutable gennem Core API, "
        "authority, durable persistence og audit. Bruger og organisation udledes af login-sessionen."
    )

    purpose = st.selectbox(
        "Formål",
        options=[item.value for item in OnboardingPurpose],
        format_func=lambda value: _PURPOSE_LABELS[value],
        key="onboarding_purpose",
    )

    with st.form("onboarding_intent_declare"):
        source_repository = st.text_input(
            "Repository identity",
            placeholder="repository:external/example",
            help="Canonical authority identity; ikke en fri glob eller wildcard.",
        )
        rationale = st.text_area(
            "Begrundelse",
            height=120,
            help="Menneskelig begrundelse for det valgte formål. Formålet infereres aldrig af en model.",
        )
        supersedes = st.text_input(
            "Supersedes intent ID (valgfri)",
            help="Bruges kun ved en correction; eksisterende intent muteres aldrig.",
        )

        target_name = None
        target_architecture = "hexagonal"
        target_language = "python"
        target_api = "fastapi"
        target_database = "postgresql"
        if purpose == OnboardingPurpose.MODERNIZE_REWRITE.value:
            st.markdown("**Target stack**")
            target_name = st.text_input("Target project name")
            target_architecture = st.selectbox(
                "Architecture",
                [item.value for item in ArchitectureKind],
            )
            target_language = st.selectbox(
                "Language",
                sorted(SUPPORTED_STACKS),
            )
            target_api = st.selectbox(
                "API/framework",
                SUPPORTED_STACKS[target_language]["api"],
            )
            target_database = st.selectbox(
                "Database",
                SUPPORTED_STACKS[target_language]["database"],
            )

        command_id = st.text_input("Command ID", value=str(uuid.uuid4()))
        submit = st.form_submit_button("Declarér onboarding intent", type="primary")

    if not submit:
        previous = st.session_state.get("onboarding_intent_result")
        if previous:
            with st.expander("Senest deklarerede onboarding intent"):
                st.json(previous)
        return

    if not source_repository.strip() or not rationale.strip() or not command_id.strip():
        st.warning("Repository identity, begrundelse og Command ID er påkrævet.")
        return

    try:
        payload = build_onboarding_payload(
            command_id=command_id.strip(),
            source_repository=source_repository.strip(),
            purpose=purpose,
            rationale=rationale.strip(),
            supersedes_intent_id=supersedes.strip() or None,
            target_name=target_name.strip() if target_name else None,
            target_architecture=target_architecture,
            target_language=target_language,
            target_api=target_api,
            target_database=target_database,
        )
        with st.spinner("Registrerer governed intent…"):
            result = client.post(
                "/api/v1/control-plane/onboarding-intents",
                json=payload,
            )
    except ValueError as exc:
        st.error(str(exc))
        return
    except DORAPIError as exc:
        st.error(f"API-fejl ({exc.status_code}): {exc}")
        return

    intent = result.get("intent", {}) if isinstance(result, dict) else {}
    st.session_state["onboarding_intent_result"] = result
    st.session_state["selected_onboarding_intent_id"] = intent.get("intent_id")
    if intent.get("organization_id"):
        st.session_state["organization_id"] = intent["organization_id"]

    replay_label = " (idempotent replay)" if result.get("replayed") else ""
    st.success(f"Onboarding intent registreret{replay_label}.")
    cols = st.columns(3)
    cols[0].metric("Purpose", intent.get("purpose", "—"))
    cols[1].metric("Declared by", intent.get("declared_by", "—"))
    cols[2].metric("Organisation", intent.get("organization_id", "—"))
    with st.expander("Immutable onboarding provenance", expanded=True):
        st.json(result)

    if intent.get("purpose") == OnboardingPurpose.AUDIT_ONLY.value:
        st.info("Audit-only intent må ikke fortsætte til scaffold/delivery.")
    else:
        st.info(
            "Intentet er nu den canonical provenance-input til Project Audit. "
            "Audit-start kræver fortsat en eksplicit governed repository execution boundary."
        )
