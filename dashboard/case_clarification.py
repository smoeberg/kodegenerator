"""Human-facing clarification capabilities inside the canonical case workbench.

This module is presentation-only. Project identity comes from the selected case,
current onboarding provenance comes from the backend, and decision choices are
rendered only from backend-provided alternatives.
"""
from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_workbench import CaseWorkbenchItem
from dashboard.user_feedback import render_api_error


_PURPOSE_LABELS = {
    "extend": "Udvid den eksisterende løsning",
    "modernize_rewrite": "Modernisér eller omskriv løsningen",
    "audit_only": "Undersøg løsningen uden at ændre den",
}
_PURPOSE_VALUES = {label: value for value, label in _PURPOSE_LABELS.items()}

_STACKS = {
    "python": {
        "api": ("fastapi", "flask", "django"),
        "database": ("postgresql", "sqlite", "mysql"),
    },
    "typescript": {
        "api": ("express", "fastify", "nestjs", "nextjs"),
        "database": ("postgresql", "sqlite", "mongodb", "mysql"),
    },
    "go": {
        "api": ("gin", "chi", "fiber"),
        "database": ("postgresql", "sqlite", "mysql"),
    },
    "php": {
        "api": ("wordpress", "laravel", "symfony", "vanilla"),
        "database": ("mysql", "mariadb", "sqlite", "none"),
    },
    "csharp": {
        "api": ("aspnetcore", "minimalapi"),
        "database": ("sqlserver", "postgresql", "sqlite"),
    },
    "rust": {
        "api": ("actix", "axum"),
        "database": ("postgresql", "sqlite"),
    },
}
_ARCHITECTURES = ("hexagonal", "clean", "modular", "plugin", "monolith")


def _as_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _current_intents(client: DORAPIClient, project_id: str) -> list[dict[str, Any]]:
    payload = client.get(
        "/api/v1/control-plane/onboarding-intents/current",
        params={"project_id": project_id},
    )
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, Mapping)]


def _intent_summary(intent: Mapping[str, Any]) -> None:
    purpose = str(intent.get("purpose") or "")
    st.markdown(f"**{intent.get('source_repository') or 'Repository ikke angivet'}**")
    st.write(_PURPOSE_LABELS.get(purpose, "Afklaring registreret"))
    rationale = str(intent.get("rationale") or "").strip()
    if rationale:
        st.caption(rationale)
    target = intent.get("target_stack")
    if isinstance(target, Mapping):
        stack = " · ".join(
            str(target.get(key) or "")
            for key in ("language", "api", "database", "architecture")
            if target.get(key)
        )
        if stack:
            st.caption(f"Mål: {stack}")


def _target_stack_fields(project_id: str) -> dict[str, str]:
    st.caption("Vælg målteknologi for moderniseringen. DOR validerer kombinationen på serveren.")
    name = st.text_input(
        "Teknisk projektnavn",
        key=f"clarification-target-name-{project_id}",
        placeholder="min-loesning",
        help="Små bogstaver, tal, - og _. Bruges kun som målkontrakt for den nye løsning.",
    )
    language = st.selectbox(
        "Sprog",
        tuple(_STACKS),
        key=f"clarification-target-language-{project_id}",
    )
    api = st.selectbox(
        "API / framework",
        _STACKS[language]["api"],
        key=f"clarification-target-api-{project_id}-{language}",
    )
    database = st.selectbox(
        "Database",
        _STACKS[language]["database"],
        key=f"clarification-target-db-{project_id}-{language}",
    )
    architecture = st.selectbox(
        "Arkitektur",
        _ARCHITECTURES,
        key=f"clarification-target-architecture-{project_id}",
    )
    return {
        "name": name.strip(),
        "language": language,
        "api": api,
        "database": database,
        "architecture": architecture,
    }


def _intent_form(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    *,
    current: Mapping[str, Any] | None,
) -> None:
    project_id = item.projection.case_id
    current_repo = str(current.get("source_repository") or "") if current else ""
    current_purpose = str(current.get("purpose") or "extend") if current else "extend"
    default_label = _PURPOSE_LABELS.get(current_purpose, _PURPOSE_LABELS["extend"])

    source_repository = st.text_input(
        "Repository",
        value=current_repo,
        key=f"clarification-repository-{project_id}-{current_repo}",
        placeholder="organisation/repository",
        disabled=current is not None,
        help="Det præcise repository som denne afklaring gælder for.",
    )
    purpose_label = st.selectbox(
        "Hvad skal DOR gøre?",
        tuple(_PURPOSE_VALUES),
        index=tuple(_PURPOSE_VALUES).index(default_label),
        key=f"clarification-purpose-{project_id}-{current_repo}",
    )
    purpose = _PURPOSE_VALUES[purpose_label]
    rationale = st.text_area(
        "Hvad vil du opnå?",
        value=str(current.get("rationale") or "") if current else "",
        key=f"clarification-rationale-{project_id}-{current_repo}",
        placeholder="Beskriv resultatet og de vigtigste hensyn med almindelige ord.",
    )

    target_stack: dict[str, str] | None = None
    if purpose == "modernize_rewrite":
        target_stack = _target_stack_fields(project_id)

    label = "Gem ændret afklaring" if current else "Gem afklaring"
    if st.button(
        label,
        type="primary",
        key=f"clarification-save-{project_id}-{current_repo or 'new'}",
        use_container_width=True,
    ):
        body: dict[str, Any] = {
            "command_id": uuid4().hex,
            "project_id": project_id,
            "source_repository": source_repository.strip(),
            "purpose": purpose,
            "rationale": rationale.strip(),
            "target_stack": target_stack,
        }
        if current and current.get("intent_id"):
            body["supersedes_intent_id"] = str(current["intent_id"])
        try:
            client.post("/api/v1/control-plane/onboarding-intents", json=body)
        except DORAPIError as exc:
            render_api_error(
                exc,
                key=f"clarification-save-error-{project_id}",
                operation="Afklaringen kunne ikke gemmes",
            )
        else:
            st.success("Afklaringen er gemt. DOR bruger den som den aktuelle hensigt for sagen.")
            st.rerun()


def render_case_onboarding(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    """Show and amend project-bound onboarding intent without exposing provenance IDs."""
    project_id = item.projection.case_id
    try:
        intents = _current_intents(client, project_id)
    except DORAPIError as exc:
        render_api_error(
            exc,
            key=f"clarification-load-{project_id}",
            operation="Afklaringen kunne ikke hentes",
        )
        return

    if not intents:
        with st.container(border=True):
            st.markdown("**Hvad skal DOR forstå om sagen?**")
            st.write(
                "Knyt sagen til det repository, DOR skal arbejde med, og beskriv resultatet. "
                "Tekniske provenance-ID'er oprettes automatisk."
            )
            _intent_form(client, item, current=None)
        return

    st.caption("DOR har følgende aktuelle afklaring registreret for sagen.")
    for intent in intents:
        with st.container(border=True):
            _intent_summary(intent)
            with st.expander("Ret afklaringen"):
                st.caption("Den tidligere version bevares som historik; DOR opretter en ny, sammenkædet version.")
                _intent_form(client, item, current=intent)

    if len(intents) > 1:
        st.info(
            "Sagen har flere repository-spor. DOR viser dem separat og vælger ikke ét af dem på dine vegne."
        )


def _risk_label(value: str) -> str:
    return {
        "LOW": "Lav risiko",
        "MEDIUM": "Mellem risiko",
        "HIGH": "Høj risiko",
        "CRITICAL": "Kritisk",
    }.get(value.upper(), "Risiko ikke angivet")


def render_case_decisions(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    """Render only backend-created pending decisions and backend-provided choices."""
    project_id = item.projection.case_id
    try:
        payload = client.get(
            "/api/v1/decisions/pending",
            params={"project_id": project_id},
        )
    except DORAPIError as exc:
        render_api_error(
            exc,
            key=f"decision-list-{project_id}",
            operation="Åbne beslutninger kunne ikke hentes",
        )
        return

    decisions = [dict(row) for row in payload if isinstance(row, Mapping)] if isinstance(payload, list) else []
    if not decisions:
        st.caption("Der er ingen åbne beslutninger, der kræver dig lige nu.")
        return

    for index, decision in enumerate(decisions):
        decision_id = str(decision.get("decision_id") or "").strip()
        alternatives = [
            dict(option)
            for option in decision.get("alternatives", [])
            if isinstance(option, Mapping) and option.get("key")
        ]
        if not decision_id or not alternatives:
            continue
        with st.container(border=True):
            st.caption(_risk_label(str(decision.get("risk_level") or "")))
            st.markdown(f"**{decision.get('question') or 'DOR har brug for en beslutning'}**")

            labels = {
                str(option["key"]): str(option.get("title") or option["key"])
                for option in alternatives
            }
            selected = st.radio(
                "Vælg retning",
                tuple(labels),
                format_func=lambda key: labels[key],
                key=f"decision-option-{decision_id}",
            )
            selected_option = next(
                option for option in alternatives if str(option["key"]) == selected
            )
            description = str(selected_option.get("description") or "").strip()
            if description:
                st.caption(description)
            rationale = st.text_area(
                "Hvorfor vælger du dette?",
                key=f"decision-rationale-{decision_id}",
                placeholder="Skriv kort, hvad beslutningen bygger på.",
            )
            if st.button(
                "Bekræft beslutning",
                type="primary" if index == 0 else "secondary",
                key=f"decision-resolve-{decision_id}",
                use_container_width=True,
            ):
                try:
                    client.post(
                        f"/api/v1/decisions/{decision_id}/resolve",
                        json={
                            "selected_alternative": selected,
                            "rationale": rationale.strip(),
                        },
                    )
                except DORAPIError as exc:
                    render_api_error(
                        exc,
                        key=f"decision-resolve-error-{decision_id}",
                        operation="Beslutningen kunne ikke gemmes",
                    )
                else:
                    st.success("Beslutningen er registreret. DOR kan nu genberegne næste skridt.")
                    st.rerun()


def render_case_clarification(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    st.markdown("#### Det har DOR forstået")
    render_case_onboarding(client, item)
    st.write("")
    st.markdown("#### Beslutninger")
    render_case_decisions(client, item)
