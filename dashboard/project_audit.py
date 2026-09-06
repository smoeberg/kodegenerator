"""Server-side Streamlit adapter for the governed read-only Project Audit runtime."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import streamlit as st

from generation.project_spec import ProjectDefinition
from phase4.onboarding import OnboardingIntent, OnboardingPurpose
from phase4.project_audit.baseline import DORBaselineProjectAuditProvider
from phase4.project_audit.repository import GitRepositoryError
from phase4.project_audit.runtime import ProjectAuditRuntime, ProjectAuditRuntimeError


class ProjectAuditGUIError(RuntimeError):
    """The GUI cannot establish the trusted inputs required for Project Audit."""


@dataclass(frozen=True)
class ProjectAuditCheckoutBinding:
    """Server-owned organization + repository + read-only checkout binding."""

    organization_id: str
    repository: str
    root: Path

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> "ProjectAuditCheckoutBinding":
        values = os.environ if environment is None else environment
        organization_id = values.get("DOR_PROJECT_AUDIT_ORGANIZATION_ID", "").strip()
        repository = values.get("DOR_PROJECT_AUDIT_REPOSITORY", "").strip()
        root_value = values.get("DOR_PROJECT_AUDIT_CHECKOUT_ROOT", "").strip()
        missing = [
            name
            for name, value in (
                ("DOR_PROJECT_AUDIT_ORGANIZATION_ID", organization_id),
                ("DOR_PROJECT_AUDIT_REPOSITORY", repository),
                ("DOR_PROJECT_AUDIT_CHECKOUT_ROOT", root_value),
            )
            if not value
        ]
        if missing:
            raise ProjectAuditGUIError(
                "Project Audit checkout er ikke konfigureret: " + ", ".join(missing)
            )
        if any(character in repository for character in "*?["):
            raise ProjectAuditGUIError(
                "DOR_PROJECT_AUDIT_REPOSITORY skal være en eksakt repository identity"
            )
        root = Path(root_value)
        if not root.is_absolute():
            raise ProjectAuditGUIError(
                "DOR_PROJECT_AUDIT_CHECKOUT_ROOT skal være en absolut server-side sti"
            )
        if not root.is_dir():
            raise ProjectAuditGUIError("Den konfigurerede Project Audit checkout findes ikke")
        return cls(
            organization_id=organization_id,
            repository=repository,
            root=root,
        )

    def root_for(self, intent: OnboardingIntent) -> Path:
        if intent.organization_id != self.organization_id:
            raise ProjectAuditGUIError(
                "Onboarding-intentets organisation matcher ikke audit-checkoutens organisation"
            )
        if intent.source_repository != self.repository:
            raise ProjectAuditGUIError(
                "Onboarding-intentets repository har ingen konfigureret audit-checkout"
            )
        return self.root.resolve()


def restore_onboarding_intent(result: Mapping[str, Any]) -> OnboardingIntent:
    """Rebuild and fingerprint-check the immutable intent returned by Core API."""
    raw = result.get("intent")
    if not isinstance(raw, Mapping):
        raise ProjectAuditGUIError("Sessionen indeholder ikke et canonical onboarding-intent")
    target_raw = raw.get("target_stack")
    target_stack = (
        ProjectDefinition.model_validate(target_raw)
        if isinstance(target_raw, Mapping)
        else None
    )
    try:
        intent = OnboardingIntent(
            source_repository=str(raw["source_repository"]),
            purpose=OnboardingPurpose(str(raw["purpose"])),
            rationale=str(raw["rationale"]),
            declared_by=str(raw["declared_by"]),
            organization_id=str(raw["organization_id"]),
            target_stack=target_stack,
            supersedes_intent_id=raw.get("supersedes_intent_id"),
            declared_at=datetime.fromisoformat(str(raw["declared_at"])),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectAuditGUIError("Onboarding-intentet kan ikke gendannes canonical") from exc
    if intent.intent_id != raw.get("intent_id"):
        raise ProjectAuditGUIError("Onboarding intent ID matcher ikke canonical indhold")
    if intent.content_fingerprint != raw.get("content_fingerprint"):
        raise ProjectAuditGUIError("Onboarding content fingerprint matcher ikke canonical indhold")
    return intent


def execute_project_audit(
    intent: OnboardingIntent,
    binding: ProjectAuditCheckoutBinding,
) -> dict[str, Any]:
    """Execute the baseline read-only audit against the server-owned checkout."""
    root = binding.root_for(intent)
    try:
        run = ProjectAuditRuntime(root).run(
            intent=intent,
            provider=DORBaselineProjectAuditProvider(),
            revision="HEAD",
        )
    except (GitRepositoryError, ProjectAuditRuntimeError, TypeError, ValueError) as exc:
        raise ProjectAuditGUIError(str(exc)) from exc

    report = run.report
    manifest = report.request.evidence_bundle.manifest
    return {
        "report_id": report.report_id,
        "authoritative": report.authoritative,
        "provider_id": report.provider_id,
        "recommendation": report.recommendation.value,
        "repository": report.request.resource,
        "commit_sha": manifest.commit_sha,
        "manifest_id": manifest.manifest_id,
        "evidence_bundle_id": report.request.evidence_bundle.bundle_id,
        "request_fingerprint": report.request.request_fingerprint,
        "objectives": list(report.request.objectives),
        "intent_id": intent.intent_id,
        "purpose": intent.purpose.value,
        "delivery_allowed": intent.purpose is not OnboardingPurpose.AUDIT_ONLY,
        "findings": [
            {
                **finding.candidate.canonical(),
                "finding_id": finding.finding_id,
            }
            for finding in report.findings
        ],
        "maturity": [item.canonical() for item in report.candidate.maturity],
    }


def _render_audit_result(result: Mapping[str, Any]) -> None:
    st.markdown("### Audit-resultat")
    cols = st.columns(4)
    cols[0].metric("Recommendation", str(result.get("recommendation", "—")))
    cols[1].metric("Findings", len(result.get("findings", [])))
    commit = str(result.get("commit_sha", "—"))
    cols[2].metric("Commit", commit[:12] if commit != "—" else commit)
    cols[3].metric("Authoritative", "Nej" if result.get("authoritative") is False else "—")

    st.warning(
        "Project Audit er rådgivende og read-only. Resultatet er ikke PASS/FAIL og autoriserer ikke execution."
    )

    maturity = result.get("maturity", [])
    if isinstance(maturity, list) and maturity:
        st.markdown("#### Maturity")
        st.dataframe(maturity, use_container_width=True, hide_index=True)

    findings = result.get("findings", [])
    if isinstance(findings, list):
        st.markdown("#### Findings")
        for finding in findings:
            if not isinstance(finding, Mapping):
                continue
            title = finding.get("title") or finding.get("key") or "Finding"
            severity = finding.get("severity", "unknown")
            with st.expander(f"{severity.upper()} · {title}"):
                st.write(finding.get("summary", ""))
                st.caption(f"Classification: {finding.get('classification', '—')}")
                if finding.get("rationale"):
                    st.markdown("**Rationale**")
                    st.write(finding["rationale"])
                consequences = finding.get("consequences") or []
                if consequences:
                    st.markdown("**Konsekvenser**")
                    for consequence in consequences:
                        st.write(f"- {consequence}")
                with st.expander("Evidens"):
                    st.json(
                        {
                            "evidence": finding.get("evidence", []),
                            "counterevidence": finding.get("counterevidence", []),
                        }
                    )

    if result.get("purpose") == OnboardingPurpose.AUDIT_ONLY.value:
        st.info("Audit-only flowet stopper her; scaffold og delivery er fortsat ikke tilladt.")
    else:
        st.info(
            "Audit-resultatet kan nu bruges som provenance i næste governed trin. "
            "Recommendation alene giver ikke execution-authority."
        )

    with st.expander("Teknisk audit-provenance", expanded=False):
        st.json(result)


def render_project_audit() -> None:
    """Render the Project Audit page from the selected immutable onboarding intent."""
    st.subheader("Project Audit")
    st.caption("Onboarding → Project Audit → governed downstream flow")

    onboarding_result = st.session_state.get("onboarding_intent_result")
    if not isinstance(onboarding_result, Mapping):
        st.warning("Der er ikke valgt et onboarding-intent i denne session.")
        st.page_link("pages/01_Onboarding.py", label="Gå til Onboarding", icon="↩️")
        return

    try:
        intent = restore_onboarding_intent(onboarding_result)
        binding = ProjectAuditCheckoutBinding.from_environment()
        binding.root_for(intent)
    except ProjectAuditGUIError as exc:
        st.error(str(exc))
        st.caption(
            "Audit-checkouten konfigureres server-side med DOR_PROJECT_AUDIT_ORGANIZATION_ID, "
            "DOR_PROJECT_AUDIT_REPOSITORY og DOR_PROJECT_AUDIT_CHECKOUT_ROOT."
        )
        st.page_link("pages/01_Onboarding.py", label="Tilbage til Onboarding", icon="↩️")
        return

    cols = st.columns(3)
    cols[0].metric("Repository", intent.source_repository)
    cols[1].metric("Purpose", intent.purpose.value)
    cols[2].metric("Intent", intent.intent_id[:12])
    st.success("Trusted read-only checkout er konfigureret til dette intent.")
    st.caption("Audit kører mod checkoutens eksakte HEAD og accepterer ingen browser-sti eller wildcard-resource.")

    if st.button("Kør Project Audit", type="primary"):
        try:
            with st.spinner("Bygger komplet Git-manifest og kører governed read-only audit…"):
                result = execute_project_audit(intent, binding)
            st.session_state["project_audit_result"] = result
            st.session_state["selected_project_audit_report_id"] = result["report_id"]
            st.success("Project Audit gennemført.")
        except ProjectAuditGUIError as exc:
            st.error(f"Project Audit blev afvist: {exc}")

    previous = st.session_state.get("project_audit_result")
    if isinstance(previous, Mapping) and previous.get("intent_id") == intent.intent_id:
        _render_audit_result(previous)

    st.page_link("pages/01_Onboarding.py", label="Tilbage til Onboarding", icon="↩️")
