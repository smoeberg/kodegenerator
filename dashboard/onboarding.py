"""Governed onboarding entrypoint for the Streamlit Control Plane."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from typing import Any, MutableMapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from generation.project_spec import ArchitectureKind, ProjectDefinition, SUPPORTED_STACKS
from phase4.onboarding import OnboardingPurpose


_PURPOSE_LABELS = {
    OnboardingPurpose.EXTEND.value: "Extend — forstå og udvid eksisterende løsning",
    OnboardingPurpose.MODERNIZE_REWRITE.value: "Modernize/rewrite — bevar adfærd på ny target stack",
    OnboardingPurpose.AUDIT_ONLY.value: "Audit only — vurder uden implementering",
}
_SUPERSEDES_INTENT_ID = re.compile(r"^[0-9a-f]{64}$")
_COMMAND_ID_KEY = "_onboarding_command_id"
_DRAFT_KEY = "_onboarding_command_draft_key"


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


def resolve_onboarding_command_id(
    state: MutableMapping[str, Any],
    payload: dict[str, Any],
) -> str:
    """Keep retries idempotent while rotating the hidden command ID for changed drafts."""
    semantic_payload = {key: value for key, value in payload.items() if key != "command_id"}
    serialized = json.dumps(
        semantic_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    draft_key = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    if state.get(_DRAFT_KEY) != draft_key or not state.get(_COMMAND_ID_KEY):
        state[_DRAFT_KEY] = draft_key
        state[_COMMAND_ID_KEY] = f"onboarding-{uuid.uuid4()}"
    return str(state[_COMMAND_ID_KEY])


def _render_result(result: dict[str, Any], *, previous: bool = False) -> None:
    intent = result.get("intent", {}) if isinstance(result, dict) else {}
    heading = "Senest registrerede onboarding-intent" if previous else "Onboarding-intent registreret"
    st.markdown(f"#### {heading}")

    cols = st.columns(3)
    cols[0].metric("Formål", intent.get("purpose", "—"))
    cols[1].metric("Deklareret af", intent.get("declared_by", "—"))
    cols[2].metric("Organisation", intent.get("organization_id", "—"))

    with st.expander("Tekniske detaljer og immutable provenance", expanded=False):
        st.json(result)

    if intent.get("purpose") == OnboardingPurpose.AUDIT_ONLY.value:
        st.info(
            "Næste trin er Project Audit. Efter audit stopper dette flow; "
            "scaffold og delivery er ikke tilladt for audit-only."
        )
    else:
        st.info(
            "Næste trin er Project Audit. Intentet er gemt i sessionen som canonical provenance-input. "
            "Audit-start kræver fortsat en eksplicit governed repository execution boundary."
        )


def render_onboarding(client: DORAPIClient) -> None:
    st.subheader("Repository onboarding")
    st.caption("1. Vælg formål · 2. Beskriv repository · 3. Registrér intent · 4. Project Audit")
    st.write(
        "Vælg formålet **før** audit. Bruger og organisation udledes automatisk af login-sessionen, "
        "og den tekniske command ID håndteres automatisk."
    )

    purpose = st.selectbox(
        "Hvad skal der ske med repository'et?",
        options=[item.value for item in OnboardingPurpose],
        format_func=lambda value: _PURPOSE_LABELS[value],
        key="onboarding_purpose",
    )

    source_repository = st.text_input(
        "Repository",
        placeholder="repository:external/example",
        help=(
            "Angiv den canonical repository identity. Repository discovery er endnu ikke koblet til GUI'en, "
            "så feltet er manuelt indtil en governed discovery-kilde findes."
        ),
        key="onboarding_source_repository",
    )
    rationale = st.text_area(
        "Hvorfor onboarder vi repository'et?",
        height=120,
        help="Begrund valget med menneskelig kontekst; formålet infereres aldrig af en model.",
        key="onboarding_rationale",
    )

    correction = st.checkbox(
        "Dette retter et tidligere onboarding-intent",
        help="Et eksisterende intent ændres aldrig; en rettelse opretter et nyt intent, som superseder det gamle.",
        key="onboarding_is_correction",
    )
    supersedes = ""
    if correction:
        supersedes = st.text_input(
            "Tidligere intent ID",
            placeholder="64-tegns intent ID",
            help="Indsæt intent ID'et, som denne deklaration erstatter.",
            key="onboarding_supersedes_intent_id",
        )

    target_name = None
    target_architecture = "hexagonal"
    target_language = "python"
    target_api = "fastapi"
    target_database = "postgresql"
    if purpose == OnboardingPurpose.MODERNIZE_REWRITE.value:
        st.markdown("#### Target stack")
        st.caption("Beskriv den ønskede målarkitektur. Valgene opdateres dynamisk efter valgt sprog.")
        target_name = st.text_input(
            "Nyt projektnavn",
            placeholder="modernized-app",
            key="onboarding_target_name",
        )
        left, right = st.columns(2)
        target_architecture = left.selectbox(
            "Arkitektur",
            [item.value for item in ArchitectureKind],
            key="onboarding_target_architecture",
        )
        target_language = right.selectbox(
            "Sprog",
            sorted(SUPPORTED_STACKS),
            key="onboarding_target_language",
        )
        left, right = st.columns(2)
        target_api = left.selectbox(
            "API/framework",
            SUPPORTED_STACKS[target_language]["api"],
            key=f"onboarding_target_api_{target_language}",
        )
        target_database = right.selectbox(
            "Database",
            SUPPORTED_STACKS[target_language]["database"],
            key=f"onboarding_target_database_{target_language}",
        )

    submit = st.button("Registrér onboarding-intent", type="primary")

    if not submit:
        previous = st.session_state.get("onboarding_intent_result")
        if isinstance(previous, dict):
            _render_result(previous, previous=True)
        return

    if not source_repository.strip() or not rationale.strip():
        st.warning("Repository og begrundelse er påkrævet.")
        return
    if correction and not _SUPERSEDES_INTENT_ID.fullmatch(supersedes.strip()):
        st.warning("Tidligere intent ID skal være et 64-tegns lowercase hex-ID.")
        return

    try:
        payload = build_onboarding_payload(
            command_id="pending",
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
        payload["command_id"] = resolve_onboarding_command_id(st.session_state, payload)
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
    st.session_state["onboarding_ready_for_project_audit"] = bool(intent.get("intent_id"))
    st.session_state["onboarding_delivery_allowed"] = (
        intent.get("purpose") != OnboardingPurpose.AUDIT_ONLY.value
    )
    if intent.get("source_repository"):
        st.session_state["selected_onboarding_repository"] = intent["source_repository"]
    if intent.get("organization_id"):
        st.session_state["organization_id"] = intent["organization_id"]

    replay_label = " (idempotent replay)" if result.get("replayed") else ""
    st.success(f"Onboarding-intent registreret{replay_label}.")
    _render_result(result)
