"""Streamlit bridge from a PASS delivery certificate to immutable traceability."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.implementation_proposal import (
    ImplementationProposalGUIError,
    restore_implementation_provenance,
)
from phase4.delivery_certificate import canonical_digest
from phase4.delivery_certification import parse_delivery_verification_candidate
from phase4.requirements_traceability import (
    CoverageClaim,
    PlanningRequirements,
    RequirementKind,
    RequirementTraceabilityError,
    canonical_planning_fingerprint,
    parse_requirement_traceability_manifest,
    requirement_sources,
)


class RequirementTraceabilityGUIError(RuntimeError):
    """The dashboard cannot establish exact traceability provenance."""


def _restore_certificate(payload: Mapping[str, Any]) -> dict[str, Any]:
    certificate = payload.get("certificate")
    if not isinstance(certificate, Mapping):
        raise RequirementTraceabilityGUIError("Delivery certificate mangler")
    canonical = dict(certificate)
    certificate_id = canonical.pop("certificate_id", None)
    if not isinstance(certificate_id, str) or canonical_digest(canonical) != certificate_id:
        raise RequirementTraceabilityGUIError(
            "Delivery certificate content identity matcher ikke certificate_id"
        )
    if canonical.get("schema_version") != 1 or canonical.get("authoritative") is not True:
        raise RequirementTraceabilityGUIError("Delivery certificate schema/authority er ugyldig")
    if canonical.get("result") != "pass" or canonical.get("reason_codes") != ["verified"]:
        raise RequirementTraceabilityGUIError(
            "Requirement traceability kræver et authoritative PASS delivery certificate"
        )
    canonical["certificate_id"] = certificate_id
    return canonical


def restore_traceability_provenance(
    *,
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
    candidate_payload: Mapping[str, Any],
    certificate_result: Mapping[str, Any],
    organization_id: str,
) -> tuple[Any, PlanningRequirements, dict[str, str], dict[str, Any]]:
    """Revalidate plan -> candidate -> PASS certificate before accepting trace links."""
    try:
        _, planning_requirements, provenance = restore_implementation_provenance(
            onboarding_result,
            audit_result,
            plan_result,
        )
        candidate = parse_delivery_verification_candidate(candidate_payload)
    except (ImplementationProposalGUIError, ValueError) as exc:
        raise RequirementTraceabilityGUIError(str(exc)) from exc
    certificate = _restore_certificate(certificate_result)
    requirements = PlanningRequirements(
        objective=planning_requirements.objective,
        acceptance_criteria=planning_requirements.acceptance_criteria,
        constraints=planning_requirements.constraints,
    )
    if not isinstance(organization_id, str) or not organization_id:
        raise RequirementTraceabilityGUIError("Aktiv organisation mangler")
    if candidate.organization_id != organization_id:
        raise RequirementTraceabilityGUIError(
            "Delivery candidate matcher ikke den aktive organisation"
        )
    if certificate.get("organization_id") != organization_id:
        raise RequirementTraceabilityGUIError(
            "Delivery certificate matcher ikke den aktive organisation"
        )
    if certificate.get("candidate_id") != candidate.candidate_id:
        raise RequirementTraceabilityGUIError(
            "Delivery certificate matcher ikke den valgte candidate"
        )
    if certificate.get("repository") != candidate.repository:
        raise RequirementTraceabilityGUIError(
            "Delivery certificate repository matcher ikke candidate"
        )
    if plan_result.get("plan_id") != candidate.plan_id:
        raise RequirementTraceabilityGUIError("AI-6 plan matcher ikke delivery candidate")
    expected_plan_fingerprint = canonical_planning_fingerprint(provenance, requirements)
    if expected_plan_fingerprint != candidate.plan_request_fingerprint:
        raise RequirementTraceabilityGUIError(
            "Planning requirements/provenance matcher ikke delivery candidate"
        )
    return candidate, requirements, provenance, certificate


def traceability_draft_fingerprint(
    *,
    certificate_id: str,
    plan_id: str,
    provenance: Mapping[str, str],
    requirements: PlanningRequirements,
    claims: tuple[CoverageClaim, ...],
) -> str:
    return canonical_digest(
        {
            "schema_version": 1,
            "certificate_id": certificate_id,
            "plan_id": plan_id,
            "planning_provenance": dict(provenance),
            "requirements": requirements.canonical(),
            "links": [
                {
                    "kind": claim.kind.value,
                    "artifact_paths": list(claim.artifact_paths),
                    "evidence_ids": list(claim.evidence_ids),
                    "rationale": claim.rationale,
                }
                for claim in sorted(claims, key=lambda item: item.kind.value)
            ],
        }
    )


def _command_id(draft_fingerprint: str) -> str:
    previous = st.session_state.get("_requirement_traceability_draft_fingerprint")
    command_id = st.session_state.get("_requirement_traceability_command_id")
    if previous != draft_fingerprint or not isinstance(command_id, str) or not command_id:
        command_id = str(uuid.uuid4())
        st.session_state["_requirement_traceability_draft_fingerprint"] = draft_fingerprint
        st.session_state["_requirement_traceability_command_id"] = command_id
    return command_id


def submit_requirement_traceability(
    client: DORAPIClient,
    *,
    organization_id: str,
    certificate_id: str,
    plan_id: str,
    provenance: Mapping[str, str],
    requirements: PlanningRequirements,
    claims: tuple[CoverageClaim, ...],
    command_id: str,
) -> dict[str, Any]:
    payload = {
        "command_id": command_id,
        "organization_id": organization_id,
        "certificate_id": certificate_id,
        "plan_id": plan_id,
        "planning_provenance": dict(provenance),
        "requirements": requirements.canonical(),
        "links": [
            {
                "kind": item.kind.value,
                "artifact_paths": list(item.artifact_paths),
                "evidence_ids": list(item.evidence_ids),
                "rationale": item.rationale,
            }
            for item in sorted(claims, key=lambda value: value.kind.value)
        ],
    }
    try:
        response = client.post(
            "/api/v1/control-plane/requirement-traceability",
            json=payload,
        )
    except DORAPIError as exc:
        raise RequirementTraceabilityGUIError(
            f"Requirement traceability blev afvist ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping) or response.get("command_id") != command_id:
        raise RequirementTraceabilityGUIError(
            "Requirement traceability response matcher ikke command_id"
        )
    manifest_payload = response.get("manifest")
    if not isinstance(manifest_payload, Mapping):
        raise RequirementTraceabilityGUIError("Backend returnerede intet traceability manifest")
    try:
        manifest = parse_requirement_traceability_manifest(manifest_payload)
    except RequirementTraceabilityError as exc:
        raise RequirementTraceabilityGUIError(str(exc)) from exc
    if (
        manifest.organization_id != organization_id
        or manifest.certificate_id != certificate_id
        or manifest.plan_id != plan_id
    ):
        raise RequirementTraceabilityGUIError(
            "Traceability manifest matcher ikke den valgte plan/certificate/tenant"
        )
    return {
        "command_id": command_id,
        "replayed": response.get("replayed") is True,
        "manifest": manifest.canonical(),
    }


def render_requirement_traceability(client: DORAPIClient) -> None:
    """Render exact requirement-to-artifact links without semantic authority inflation."""
    st.subheader("Requirement → Artifact Traceability")
    st.caption(
        "Human requirements → AI-6 fingerprint → PASS certificate → certified artifact/evidence links"
    )

    onboarding_result = st.session_state.get("onboarding_intent_result")
    audit_result = st.session_state.get("project_audit_result")
    plan_result = st.session_state.get("project_plan_result")
    candidate_payload = st.session_state.get("delivery_verification_candidate")
    certificate_result = st.session_state.get("delivery_certificate_result")
    organization_id = st.session_state.get("organization_id")
    values = (
        onboarding_result,
        audit_result,
        plan_result,
        candidate_payload,
        certificate_result,
    )
    if not all(isinstance(value, Mapping) for value in values) or not isinstance(
        organization_id, str
    ):
        st.warning("Et authoritative PASS Delivery Certificate er påkrævet før traceability.")
        st.page_link(
            "pages/07_Delivery_Certificate.py",
            label="Gå til Delivery Certificate",
            icon="↩️",
        )
        return

    try:
        candidate, requirements, provenance, certificate = restore_traceability_provenance(
            onboarding_result=onboarding_result,
            audit_result=audit_result,
            plan_result=plan_result,
            candidate_payload=candidate_payload,
            certificate_result=certificate_result,
            organization_id=organization_id,
        )
    except RequirementTraceabilityGUIError as exc:
        st.error(str(exc))
        return

    sources = requirement_sources(
        plan_request_fingerprint=candidate.plan_request_fingerprint,
        requirements=requirements,
    )
    artifact_paths = [item.path for item in candidate.files]
    evidence_ids = list(candidate.evidence_ids)

    cols = st.columns(4)
    cols[0].metric("Repository", candidate.repository)
    cols[1].metric("Plan", candidate.plan_id[:12])
    cols[2].metric("Certificate", str(certificate["certificate_id"])[:12])
    cols[3].metric("Requirements", len(sources))
    st.warning(
        "Traceability verificerer reference-integritet, ikke semantisk opfyldelse. "
        "Et link betyder 'dette artifact/evidence er relevant for kravet' — ikke automatisk 'kravet er bevist opfyldt'."
    )

    claims: list[CoverageClaim] = []
    for source in sources:
        st.markdown(f"### {source.kind.value.replace('_', ' ').title()}")
        st.write(source.text)
        selected_paths = st.multiselect(
            "Certified artifact paths",
            options=artifact_paths,
            key=f"requirement_traceability_paths_{source.kind.value}",
            help="Kun paths fra det PASS-certificerede artifact kan vælges.",
        )
        selected_evidence = st.multiselect(
            "Certified tool evidence IDs (valgfrit)",
            options=evidence_ids,
            format_func=lambda value: value[:12],
            key=f"requirement_traceability_evidence_{source.kind.value}",
            help="Lint/test/build evidence er supporting trace evidence; det er ikke criterion-specific semantic proof.",
        )
        rationale = st.text_area(
            "Trace rationale (valgfrit)",
            max_chars=2_000,
            key=f"requirement_traceability_rationale_{source.kind.value}",
            help="Forklar hvorfor de valgte artifact/evidence-referencer er relevante.",
        )
        try:
            claims.append(
                CoverageClaim(
                    kind=source.kind,
                    artifact_paths=tuple(selected_paths),
                    evidence_ids=tuple(selected_evidence),
                    rationale=rationale.strip(),
                )
            )
        except RequirementTraceabilityError as exc:
            st.error(str(exc))
            return

    claim_tuple = tuple(claims)
    draft_fingerprint = traceability_draft_fingerprint(
        certificate_id=str(certificate["certificate_id"]),
        plan_id=candidate.plan_id,
        provenance=provenance,
        requirements=requirements,
        claims=claim_tuple,
    )
    command_id = _command_id(draft_fingerprint)
    linked = sum(1 for item in claim_tuple if item.linked)
    evidenced = sum(1 for item in claim_tuple if item.evidenced)
    summary_cols = st.columns(3)
    summary_cols[0].metric("Linked", f"{linked}/{len(claim_tuple)}")
    summary_cols[1].metric("Evidenced", f"{evidenced}/{len(claim_tuple)}")
    summary_cols[2].metric(
        "Coverage",
        "COMPLETE" if linked == len(claim_tuple) else "PARTIAL",
    )

    confirmed = st.checkbox(
        "Jeg bekræfter, at dette kun er requirement-to-artifact traceability og ikke en semantisk PASS/release-beslutning",
        key="requirement_traceability_confirmed",
    )
    if st.button(
        "Gem immutable traceability manifest",
        type="primary",
        disabled=not confirmed,
    ):
        try:
            result = submit_requirement_traceability(
                client,
                organization_id=organization_id,
                certificate_id=str(certificate["certificate_id"]),
                plan_id=candidate.plan_id,
                provenance=provenance,
                requirements=requirements,
                claims=claim_tuple,
                command_id=command_id,
            )
            st.session_state["requirement_traceability_result"] = result
            st.session_state["selected_requirement_traceability_manifest_id"] = result[
                "manifest"
            ]["manifest_id"]
        except RequirementTraceabilityGUIError as exc:
            st.error(str(exc))

    result = st.session_state.get("requirement_traceability_result")
    if isinstance(result, Mapping):
        manifest = result.get("manifest")
        if (
            isinstance(manifest, Mapping)
            and manifest.get("certificate_id") == certificate.get("certificate_id")
            and manifest.get("plan_id") == candidate.plan_id
        ):
            if manifest.get("status") == "complete":
                st.success("COMPLETE — alle planning source requirements har artifact-links.")
            else:
                st.warning("PARTIAL — mindst ét planning source requirement mangler artifact-link.")
            st.info(
                "semantic_result = null og release_authority = false. Manifestet dokumenterer traceability, ikke semantic acceptance."
            )
            st.code(
                json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False),
                language="json",
            )
            if result.get("replayed") is True:
                st.caption("Serveren returnerede det eksisterende immutable manifest (replay).")

    st.page_link(
        "pages/07_Delivery_Certificate.py",
        label="Tilbage til Delivery Certificate",
        icon="↩️",
    )
