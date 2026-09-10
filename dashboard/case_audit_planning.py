"""Case-bound Project Audit and Requirements/Plan experience.

The canonical case workbench reuses the governed read-only Project Audit and
non-authoritative AI-6 planner while binding every cached presentation artifact
to the selected project and exact immutable onboarding intent. Browser input
never supplies filesystem paths or authority decisions.
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Any

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_workbench import CaseWorkbenchItem
from dashboard.project_audit import (
    ProjectAuditGUIError,
    execute_project_audit,
    restore_onboarding_intent,
)
from dashboard.project_planning import (
    ProjectPlanningGUIError,
    ProjectPlanningInput,
    generate_project_plan,
)
from dashboard.repository_checkout_catalog import (
    RepositoryCheckoutCatalogError,
    discover_repository_checkout,
)
from dashboard.user_feedback import render_api_error
from phase4.onboarding import OnboardingIntent, OnboardingPurpose


_AUDIT_CACHE_KEY = "case_audit_results"
_PLAN_CACHE_KEY = "case_plan_results"

_RECOMMENDATION_COPY: dict[str, tuple[str, str]] = {
    "continue": (
        "Analysen understøtter næste skridt",
        "DOR fandt ikke et forhold, der i sig selv kræver en ny plan. Analysen er stadig rådgivende.",
    ),
    "continue_with_gaps": (
        "I kan fortsætte med opmærksomhedspunkter",
        "Der er kendte huller, som bør indgå i krav og plan, men auditten giver ikke execution-authority.",
    ),
    "replan": (
        "Planen bør justeres før implementering",
        "Auditten peger på forhold, der bør omsættes til krav eller begrænsninger, før arbejdet fortsætter.",
    ),
    "escalate": (
        "Kræver menneskelig afklaring",
        "Auditten har fundet et forhold, som bør afklares, før næste leveringsskridt vælges.",
    ),
}

_SEVERITY_LABELS = {
    "info": "Info",
    "low": "Lav",
    "medium": "Mellem",
    "high": "Høj",
    "critical": "Kritisk",
}


def _track_key(project_id: str, intent_id: str) -> str:
    return f"{project_id}:{intent_id}"


def _cache(name: str) -> MutableMapping[str, dict[str, Any]]:
    current = st.session_state.get(name)
    if not isinstance(current, dict):
        current = {}
        st.session_state[name] = current
    return current


def _current_intents(client: DORAPIClient, project_id: str) -> list[dict[str, Any]]:
    payload = client.get(
        "/api/v1/control-plane/onboarding-intents/current",
        params={"project_id": project_id},
    )
    if not isinstance(payload, list):
        return []
    return [dict(value) for value in payload if isinstance(value, Mapping)]


def restore_case_intent(raw: Mapping[str, Any], *, project_id: str) -> OnboardingIntent:
    """Restore one backend-owned current intent and require exact case ownership."""
    intent = restore_onboarding_intent({"intent": dict(raw)})
    if intent.project_id != project_id:
        raise ProjectAuditGUIError(
            "Afklaringen er ikke bundet til den valgte sag. Hent den aktuelle sag igen."
        )
    return intent


def audit_matches_case(
    result: Mapping[str, Any],
    *,
    project_id: str,
    intent: OnboardingIntent,
) -> bool:
    """True only for an audit cached for this exact case + intent leaf."""
    return (
        result.get("project_id") == project_id
        and result.get("intent_id") == intent.intent_id
        and result.get("repository") == intent.source_repository
        and result.get("authoritative") is False
    )


def plan_matches_case(
    result: Mapping[str, Any],
    *,
    project_id: str,
    intent: OnboardingIntent,
    audit: Mapping[str, Any],
) -> bool:
    """True only when a non-authoritative plan is bound to the exact audit."""
    provenance = result.get("provenance")
    return (
        isinstance(provenance, Mapping)
        and result.get("project_id") == project_id
        and result.get("authoritative") is False
        and result.get("executable") is False
        and result.get("resource") == intent.source_repository
        and provenance.get("intent_id") == intent.intent_id
        and provenance.get("report_id") == audit.get("report_id")
    )


def _cached_audit(project_id: str, intent: OnboardingIntent) -> dict[str, Any] | None:
    value = _cache(_AUDIT_CACHE_KEY).get(_track_key(project_id, intent.intent_id))
    if isinstance(value, Mapping) and audit_matches_case(
        value,
        project_id=project_id,
        intent=intent,
    ):
        return dict(value)
    return None


def _cached_plan(
    project_id: str,
    intent: OnboardingIntent,
    audit: Mapping[str, Any],
) -> dict[str, Any] | None:
    value = _cache(_PLAN_CACHE_KEY).get(_track_key(project_id, intent.intent_id))
    if isinstance(value, Mapping) and plan_matches_case(
        value,
        project_id=project_id,
        intent=intent,
        audit=audit,
    ):
        return dict(value)
    return None


def _store_audit(project_id: str, intent: OnboardingIntent, result: Mapping[str, Any]) -> None:
    payload = {**dict(result), "project_id": project_id}
    if not audit_matches_case(payload, project_id=project_id, intent=intent):
        raise ProjectAuditGUIError("Audit-resultatet kunne ikke bindes sikkert til sagen.")
    _cache(_AUDIT_CACHE_KEY)[_track_key(project_id, intent.intent_id)] = payload
    _cache(_PLAN_CACHE_KEY).pop(_track_key(project_id, intent.intent_id), None)


def _store_plan(
    project_id: str,
    intent: OnboardingIntent,
    audit: Mapping[str, Any],
    result: Mapping[str, Any],
) -> None:
    payload = {**dict(result), "project_id": project_id}
    if not plan_matches_case(
        payload,
        project_id=project_id,
        intent=intent,
        audit=audit,
    ):
        raise ProjectPlanningGUIError("Planforslaget kunne ikke bindes sikkert til sagen.")
    _cache(_PLAN_CACHE_KEY)[_track_key(project_id, intent.intent_id)] = payload


def _recommendation(result: Mapping[str, Any]) -> tuple[str, str]:
    value = str(result.get("recommendation") or "").lower()
    return _RECOMMENDATION_COPY.get(
        value,
        (
            "Audit gennemført",
            "DOR har gennemført den rådgivende analyse. Se fundene nedenfor før næste skridt.",
        ),
    )


def _render_audit_summary(result: Mapping[str, Any]) -> None:
    title, explanation = _recommendation(result)
    findings = [item for item in result.get("findings", []) if isinstance(item, Mapping)]
    high_attention = sum(
        1
        for finding in findings
        if str(finding.get("severity") or "").lower() in {"high", "critical"}
    )
    maturity = [item for item in result.get("maturity", []) if isinstance(item, Mapping)]
    achieved = sum(1 for item in maturity if str(item.get("status") or "") == "achieved")

    with st.container(border=True):
        st.markdown(f"**{title}**")
        st.write(explanation)
        cols = st.columns(3)
        cols[0].metric("Fund", len(findings))
        cols[1].metric("Kræver ekstra opmærksomhed", high_attention)
        cols[2].metric("Modenhed opfyldt", f"{achieved}/{len(maturity)}" if maturity else "—")
        st.caption("Project Audit er read-only og rådgivende. Den starter eller autoriserer ikke arbejde.")

    if findings:
        st.markdown("**Det vigtigste fra analysen**")
        for finding in findings[:8]:
            severity = str(finding.get("severity") or "info").lower()
            title = str(finding.get("title") or finding.get("key") or "Observation")
            summary = str(finding.get("summary") or "").strip()
            label = _SEVERITY_LABELS.get(severity, "Observation")
            with st.container(border=True):
                st.caption(label)
                st.markdown(f"**{title}**")
                if summary:
                    st.write(summary)
                consequences = finding.get("consequences")
                if isinstance(consequences, list) and consequences:
                    st.caption("Betydning: " + " · ".join(str(value) for value in consequences[:3]))

    with st.expander("Tekniske auditdetaljer"):
        st.caption("Fingerprints, manifest og evidens er skjult i den normale arbejdsoplevelse.")
        st.json(result)


def _render_plan(result: Mapping[str, Any]) -> None:
    st.markdown("**Planforslag**")
    st.caption("AI-6 foreslår rækkefølgen. Planen er ikke execution-authority.")
    steps = result.get("steps")
    if isinstance(steps, list):
        for index, step in enumerate(steps, start=1):
            st.write(f"{index}. {step}")

    confidence = result.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        normalized = max(0.0, min(float(confidence), 1.0))
        st.progress(normalized, text=f"Planens confidence: {normalized:.0%}")
    rationale = str(result.get("rationale") or "").strip()
    if rationale:
        st.markdown("**Hvorfor denne plan?**")
        st.write(rationale)

    with st.expander("Tekniske plandetaljer"):
        st.json(result)


def _render_planning_form(
    *,
    project_id: str,
    intent: OnboardingIntent,
    intent_payload: Mapping[str, Any],
    audit: Mapping[str, Any],
    existing: Mapping[str, Any] | None,
) -> None:
    requirements = existing.get("requirements") if isinstance(existing, Mapping) else None
    requirements = requirements if isinstance(requirements, Mapping) else {}

    st.markdown("**Krav til næste ændring**")
    st.write("Beskriv resultatet med almindelige ord. DOR binder kravene til den aktuelle audit.")
    with st.form(f"case-planning-{_track_key(project_id, intent.intent_id)}"):
        objective = st.text_area(
            "Hvad skal ændringen opnå?",
            value=str(requirements.get("objective") or ""),
            max_chars=4000,
            placeholder="Beskriv det konkrete resultat, som skal leveres.",
        )
        acceptance = st.text_area(
            "Hvornår er resultatet godt nok?",
            value=str(requirements.get("acceptance_criteria") or ""),
            max_chars=4000,
            placeholder="Beskriv observerbare acceptkriterier.",
        )
        constraints = st.text_area(
            "Begrænsninger eller hensyn (valgfrit)",
            value=str(requirements.get("constraints") or ""),
            max_chars=4000,
            placeholder="Fx kompatibilitet, sikkerhed, teknologi eller scope.",
        )
        submitted = st.form_submit_button(
            "Opdatér planforslag" if existing else "Opret planforslag",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        try:
            declared = ProjectPlanningInput(
                objective=objective.strip(),
                acceptance_criteria=acceptance.strip(),
                constraints=constraints.strip(),
            )
            result = generate_project_plan(
                {"intent": dict(intent_payload)},
                dict(audit),
                declared,
            )
            _store_plan(project_id, intent, audit, result)
        except (ProjectPlanningGUIError, ValueError) as exc:
            st.error(f"Planen kunne ikke oprettes: {exc}")
        else:
            st.success("Planforslaget er oprettet og bundet til den aktuelle audit.")
            st.rerun()


def _render_track(
    *,
    project_id: str,
    intent_payload: Mapping[str, Any],
    primary: bool,
) -> None:
    try:
        intent = restore_case_intent(intent_payload, project_id=project_id)
    except ProjectAuditGUIError as exc:
        st.error(str(exc))
        return

    st.markdown(f"### {intent.source_repository}")
    if intent.purpose is OnboardingPurpose.AUDIT_ONLY:
        st.caption("Undersøgelse uden ændringer")
    else:
        st.caption("Analyse → krav → plan")

    audit = _cached_audit(project_id, intent)
    if audit is None:
        st.write(
            "DOR kan nu analysere det server-bundne repository read-only. Browseren vælger ingen sti eller checkout."
        )
        if st.button(
            "Kør rådgivende analyse",
            type="primary" if primary else "secondary",
            key=f"case-audit-run-{_track_key(project_id, intent.intent_id)}",
            use_container_width=True,
        ):
            try:
                binding = discover_repository_checkout(
                    organization_id=intent.organization_id,
                    repository=intent.source_repository,
                )
                with st.spinner("DOR analyserer repository read-only…"):
                    result = execute_project_audit(intent, binding)
                _store_audit(project_id, intent, result)
            except (ProjectAuditGUIError, RepositoryCheckoutCatalogError) as exc:
                st.error(
                    "Analysen kunne ikke gennemføres. DOR kunne ikke etablere den server-ejede repository-binding."
                )
                with st.expander("Tekniske detaljer"):
                    st.code(str(exc))
            else:
                st.success("Analysen er gennemført.")
                st.rerun()
        return

    _render_audit_summary(audit)

    if intent.purpose is OnboardingPurpose.AUDIT_ONLY:
        st.info(
            "Denne sag er markeret som audit-only. Flowet stopper efter analysen og tilbyder ikke implementering eller levering."
        )
        return

    plan = _cached_plan(project_id, intent, audit)
    if plan is not None:
        _render_plan(plan)
        st.write("")
    _render_planning_form(
        project_id=project_id,
        intent=intent,
        intent_payload=intent_payload,
        audit=audit,
        existing=plan,
    )


def render_case_audit_planning(client: DORAPIClient, item: CaseWorkbenchItem) -> None:
    """Render Project Audit + Requirements/Plan for the selected case only."""
    project_id = item.projection.case_id
    try:
        intents = _current_intents(client, project_id)
    except DORAPIError as exc:
        render_api_error(
            exc,
            key=f"case-audit-intents-{project_id}",
            operation="Analysegrundlaget kunne ikke hentes",
        )
        return

    st.markdown("#### Analyse og plan")
    if not intents:
        st.caption("Gem først afklaringen ovenfor. Derefter kan DOR analysere repository og foreslå en plan.")
        return

    if len(intents) > 1:
        st.info(
            "Sagen har flere aktuelle repository-spor. DOR analyserer dem hver for sig og vælger ikke et spor på dine vegne."
        )

    for index, intent_payload in enumerate(intents):
        _render_track(
            project_id=project_id,
            intent_payload=intent_payload,
            primary=index == 0,
        )
        if index < len(intents) - 1:
            st.divider()
