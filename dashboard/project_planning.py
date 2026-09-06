"""Governed non-executing planning bridge from Project Audit to AI-6."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

import streamlit as st

from dashboard.project_audit import ProjectAuditGUIError, restore_onboarding_intent
from phase4.onboarding import OnboardingIntent, OnboardingPurpose
from phase4.planner.service import PlanParseError, PlannerService


_MAX_REQUIREMENT_CHARS = 4000


class ProjectPlanningGUIError(RuntimeError):
    """Planning cannot establish exact immutable upstream provenance."""


@dataclass(frozen=True)
class ProjectPlanningInput:
    """Human-declared planning requirements, separate from audit authority."""

    objective: str
    acceptance_criteria: str
    constraints: str = ""

    def __post_init__(self) -> None:
        for name in ("objective", "acceptance_criteria"):
            value = getattr(self, name)
            if not value or value != value.strip():
                raise ValueError(f"{name} skal være ikke-tom canonical tekst")
        for name in ("objective", "acceptance_criteria", "constraints"):
            value = getattr(self, name)
            if len(value) > _MAX_REQUIREMENT_CHARS:
                raise ValueError(
                    f"{name} må højst være {_MAX_REQUIREMENT_CHARS} tegn"
                )
        if self.constraints != self.constraints.strip():
            raise ValueError("constraints skal være canonical tekst uden outer whitespace")

    def canonical(self) -> dict[str, str]:
        return {
            "objective": self.objective,
            "acceptance_criteria": self.acceptance_criteria,
            "constraints": self.constraints,
        }


def restore_planning_provenance(
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
) -> tuple[OnboardingIntent, dict[str, str]]:
    """Validate that one advisory audit belongs exactly to one onboarding intent."""
    try:
        intent = restore_onboarding_intent(onboarding_result)
    except ProjectAuditGUIError as exc:
        raise ProjectPlanningGUIError(str(exc)) from exc

    if intent.purpose is OnboardingPurpose.AUDIT_ONLY:
        raise ProjectPlanningGUIError(
            "Audit-only intent må ikke fortsætte til requirements eller planning"
        )
    if audit_result.get("authoritative") is not False:
        raise ProjectPlanningGUIError(
            "Project Audit provenance skal være eksplicit non-authoritative"
        )
    if audit_result.get("delivery_allowed") is not True:
        raise ProjectPlanningGUIError(
            "Project Audit provenance tillader ikke downstream planning"
        )
    if audit_result.get("intent_id") != intent.intent_id:
        raise ProjectPlanningGUIError(
            "Project Audit report matcher ikke det valgte onboarding-intent"
        )
    if audit_result.get("purpose") != intent.purpose.value:
        raise ProjectPlanningGUIError("Project Audit purpose matcher ikke onboarding-intentet")
    if audit_result.get("repository") != intent.source_repository:
        raise ProjectPlanningGUIError(
            "Project Audit repository matcher ikke onboarding-intentets repository"
        )

    provenance = {
        "intent_id": intent.intent_id,
        "content_fingerprint": intent.content_fingerprint,
        "report_id": _required_text(audit_result, "report_id"),
        "audit_request_fingerprint": _required_text(
            audit_result, "request_fingerprint"
        ),
        "manifest_id": _required_text(audit_result, "manifest_id"),
        "evidence_bundle_id": _required_text(audit_result, "evidence_bundle_id"),
        "commit_sha": _required_text(audit_result, "commit_sha"),
        "repository": intent.source_repository,
        "purpose": intent.purpose.value,
        "recommendation": _required_text(audit_result, "recommendation"),
    }
    return intent, provenance


def planning_fingerprint(
    provenance: Mapping[str, str],
    requirements: ProjectPlanningInput,
) -> str:
    """Bind the human planning declaration to the exact advisory audit evidence."""
    payload = {
        "schema_version": 1,
        "provenance": dict(provenance),
        "requirements": requirements.canonical(),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_planning_spec(
    intent: OnboardingIntent,
    audit_result: Mapping[str, Any],
    requirements: ProjectPlanningInput,
) -> dict[str, Any]:
    """Build a bounded AI-6 spec without converting audit advice into authority."""
    steps = [f"Plan the declared scope: {requirements.objective}"]
    findings = audit_result.get("findings", [])
    if isinstance(findings, list):
        for finding in findings[:6]:
            if not isinstance(finding, Mapping):
                continue
            title = str(finding.get("title") or finding.get("key") or "finding").strip()
            severity = str(finding.get("severity") or "unknown").strip()
            if title:
                steps.append(
                    f"Review advisory Project Audit finding ({severity}): {title}"
                )
    steps.append(f"Verify declared acceptance criteria: {requirements.acceptance_criteria}")
    if requirements.constraints:
        steps.append(f"Respect declared constraints: {requirements.constraints}")

    target_stack = (
        intent.target_stack.model_dump(mode="json")
        if intent.target_stack is not None
        else None
    )
    spec: dict[str, Any] = {
        "title": f"Plan for {intent.source_repository}",
        "description": requirements.objective,
        "action": intent.purpose.value,
        "resource": intent.source_repository,
        "steps": steps[:16],
        "acceptance_criteria": requirements.acceptance_criteria,
        "constraints": requirements.constraints,
        "audit_recommendation": str(audit_result.get("recommendation") or "unknown"),
    }
    if target_stack is not None:
        spec["target_stack"] = target_stack
        spec["language"] = target_stack.get("language")
    return spec


def generate_project_plan(
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    requirements: ProjectPlanningInput,
) -> dict[str, Any]:
    """Create an immutable proposed-only AI-6 plan bound to audit provenance."""
    intent, provenance = restore_planning_provenance(onboarding_result, audit_result)
    fingerprint = planning_fingerprint(provenance, requirements)
    spec = build_planning_spec(intent, audit_result, requirements)
    try:
        plan = PlannerService().plan_from_spec(spec, fingerprint=fingerprint)
    except (PlanParseError, TypeError, ValueError) as exc:
        raise ProjectPlanningGUIError(str(exc)) from exc

    if plan.request_fingerprint != fingerprint:
        raise ProjectPlanningGUIError(
            "AI-6 planens request fingerprint matcher ikke den governed planning-input"
        )
    if plan.resource != intent.source_repository:
        raise ProjectPlanningGUIError(
            "AI-6 planen forsøgte at ændre den bundne repository resource"
        )

    return {
        "plan_id": plan.plan_id,
        "status": plan.status.value,
        "authoritative": False,
        "executable": False,
        "request_fingerprint": plan.request_fingerprint,
        "resource": plan.resource,
        "action": plan.action,
        "steps": list(plan.steps),
        "rationale": plan.rationale,
        "confidence": plan.confidence,
        "created_at": plan.created_at,
        "requirements": requirements.canonical(),
        "provenance": provenance,
    }


def _render_plan(result: Mapping[str, Any]) -> None:
    st.markdown("### Planforslag")
    cols = st.columns(4)
    cols[0].metric("Status", str(result.get("status", "—")))
    cols[1].metric("Steps", len(result.get("steps", [])))
    cols[2].metric("Executable", "Nej")
    cols[3].metric("Authoritative", "Nej")
    st.warning(
        "AI-6 planen er kun et forslag. Den giver ingen execution-authority og starter ikke arbejde automatisk."
    )
    steps = result.get("steps", [])
    if isinstance(steps, list):
        for index, step in enumerate(steps, start=1):
            st.write(f"{index}. {step}")
    if result.get("rationale"):
        st.markdown("**Rationale**")
        st.write(result["rationale"])
    with st.expander("Teknisk planning-provenance", expanded=False):
        st.json(result)


def render_project_planning() -> None:
    """Render human requirements and a non-executing AI-6 plan proposal."""
    st.subheader("Requirements & Plan")
    st.caption("Onboarding → Project Audit → Requirements → AI-6 plan proposal")

    onboarding_result = st.session_state.get("onboarding_intent_result")
    audit_result = st.session_state.get("project_audit_result")
    if not isinstance(onboarding_result, Mapping) or not isinstance(audit_result, Mapping):
        st.warning("Et gennemført Project Audit er påkrævet før planning.")
        st.page_link("pages/02_Project_Audit.py", label="Gå til Project Audit", icon="↩️")
        return

    try:
        intent, provenance = restore_planning_provenance(onboarding_result, audit_result)
    except ProjectPlanningGUIError as exc:
        st.error(str(exc))
        st.page_link("pages/02_Project_Audit.py", label="Tilbage til Project Audit", icon="↩️")
        return

    cols = st.columns(3)
    cols[0].metric("Repository", intent.source_repository)
    cols[1].metric("Audit", provenance["report_id"][:12])
    cols[2].metric("Commit", provenance["commit_sha"][:12])
    st.caption(
        f"Audit recommendation: {provenance['recommendation']} — advisory only; den bruges som provenance, ikke authority."
    )

    objective = st.text_area(
        "Hvad skal næste ændring opnå?",
        height=120,
        max_chars=_MAX_REQUIREMENT_CHARS,
        key="project_planning_objective",
    )
    acceptance = st.text_area(
        "Acceptance criteria",
        height=120,
        max_chars=_MAX_REQUIREMENT_CHARS,
        help="Beskriv observerbare kriterier, som senere verification kan måle imod.",
        key="project_planning_acceptance_criteria",
    )
    constraints = st.text_area(
        "Constraints (valgfrit)",
        height=90,
        max_chars=_MAX_REQUIREMENT_CHARS,
        key="project_planning_constraints",
    )

    if st.button("Opret planforslag", type="primary"):
        try:
            requirements = ProjectPlanningInput(
                objective=objective.strip(),
                acceptance_criteria=acceptance.strip(),
                constraints=constraints.strip(),
            )
            result = generate_project_plan(onboarding_result, audit_result, requirements)
            st.session_state["project_plan_result"] = result
            st.session_state["selected_project_plan_id"] = result["plan_id"]
            st.success("Governed AI-6 planforslag oprettet.")
        except (ProjectPlanningGUIError, ValueError) as exc:
            st.error(str(exc))

    previous = st.session_state.get("project_plan_result")
    if (
        isinstance(previous, Mapping)
        and isinstance(previous.get("provenance"), Mapping)
        and previous["provenance"].get("intent_id") == intent.intent_id
        and previous["provenance"].get("report_id") == provenance["report_id"]
    ):
        _render_plan(previous)

    st.page_link("pages/02_Project_Audit.py", label="Tilbage til Project Audit", icon="↩️")


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProjectPlanningGUIError(f"Project Audit provenance mangler {key}")
    return value.strip()
