"""Streamlit review and human acceptance of one exact multi-spec artifact bundle."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from phase4.artifact_acceptance import (
    ArtifactAcceptanceError,
    artifact_acceptance_request_fingerprint,
    parse_multi_spec_artifact_acceptance,
)
from phase4.delivery_certificate import canonical_digest
from phase4.requirements_traceability import (
    RequirementTraceabilityError,
    parse_requirement_traceability_manifest,
)


class ArtifactAcceptanceGUIError(RuntimeError):
    """The dashboard cannot establish an exact multi-spec acceptance response."""


def load_eligible_manifest_catalog(
    client: DORAPIClient,
    *,
    organization_id: str,
    repository: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"organization_id": organization_id, "limit": 100}
    if repository:
        params["repository"] = repository
    try:
        response = client.get(
            "/api/v1/control-plane/artifact-acceptances/eligible-manifests",
            params=params,
        )
    except DORAPIError as exc:
        raise ArtifactAcceptanceGUIError(
            f"Traceability-katalog kunne ikke hentes ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping) or not isinstance(response.get("manifests"), list):
        raise ArtifactAcceptanceGUIError("Traceability-katalog response er malformed")
    result: list[dict[str, Any]] = []
    for item in response["manifests"]:
        if not isinstance(item, Mapping):
            raise ArtifactAcceptanceGUIError("Traceability-katalog indeholder malformed entry")
        required = (
            "manifest_id",
            "repository",
            "plan_id",
            "plan_request_fingerprint",
            "certificate_id",
            "candidate_id",
            "status",
            "requirement_count",
            "created_by",
            "created_at",
        )
        if any(key not in item for key in required) or item.get("status") != "complete":
            raise ArtifactAcceptanceGUIError("Traceability-katalog entry er ikke COMPLETE/canonical")
        manifest_id = item.get("manifest_id")
        plan_fingerprint = item.get("plan_request_fingerprint")
        if not _is_digest(manifest_id) or not _is_digest(plan_fingerprint):
            raise ArtifactAcceptanceGUIError("Traceability-katalog indeholder ugyldig content ID")
        result.append(dict(item))
    return result


def load_traceability_manifest(
    client: DORAPIClient,
    *,
    organization_id: str,
    manifest_id: str,
) -> dict[str, Any]:
    try:
        response = client.get(
            f"/api/v1/control-plane/requirement-traceability/{manifest_id}",
            params={"organization_id": organization_id},
        )
    except DORAPIError as exc:
        raise ArtifactAcceptanceGUIError(
            f"Traceability manifest kunne ikke hentes ({exc.status_code}): {exc}"
        ) from exc
    payload = response.get("manifest") if isinstance(response, Mapping) else None
    if not isinstance(payload, Mapping):
        raise ArtifactAcceptanceGUIError("Backend returnerede intet traceability manifest")
    try:
        manifest = parse_requirement_traceability_manifest(payload)
    except RequirementTraceabilityError as exc:
        raise ArtifactAcceptanceGUIError(str(exc)) from exc
    if manifest.organization_id != organization_id or manifest.status.value != "complete":
        raise ArtifactAcceptanceGUIError(
            "Traceability manifest matcher ikke aktiv organisation/COMPLETE status"
        )
    return manifest.canonical()


def acceptance_draft_fingerprint(
    *,
    organization_id: str,
    manifest_ids: tuple[str, ...],
    rationale: str,
) -> str:
    ids = tuple(sorted(manifest_ids))
    if len(ids) < 2 or len(ids) != len(set(ids)):
        raise ArtifactAcceptanceGUIError("Vælg mindst to unikke traceability manifests")
    for manifest_id in ids:
        if not _is_digest(manifest_id):
            raise ArtifactAcceptanceGUIError("Traceability manifest ID er ugyldigt")
    if not isinstance(rationale, str) or rationale != rationale.strip():
        raise ArtifactAcceptanceGUIError("Acceptance rationale skal være canonical tekst")
    return canonical_digest(
        {
            "schema_version": 1,
            "organization_id": organization_id,
            "manifest_ids": list(ids),
            "acceptance_assertion": "accept_exact_multi_spec_artifact_bundle",
            "rationale": rationale,
        }
    )


def _command_id(draft_fingerprint: str) -> str:
    previous = st.session_state.get("_artifact_acceptance_draft_fingerprint")
    command_id = st.session_state.get("_artifact_acceptance_command_id")
    if previous != draft_fingerprint or not isinstance(command_id, str) or not command_id:
        command_id = str(uuid.uuid4())
        st.session_state["_artifact_acceptance_draft_fingerprint"] = draft_fingerprint
        st.session_state["_artifact_acceptance_command_id"] = command_id
    return command_id


def submit_artifact_acceptance(
    client: DORAPIClient,
    *,
    organization_id: str,
    manifest_ids: tuple[str, ...],
    rationale: str,
    command_id: str,
) -> dict[str, Any]:
    try:
        response = client.post(
            "/api/v1/control-plane/artifact-acceptances",
            json={
                "command_id": command_id,
                "organization_id": organization_id,
                "manifest_ids": list(sorted(manifest_ids)),
                "acceptance_assertion": "accept_exact_multi_spec_artifact_bundle",
                "rationale": rationale,
            },
        )
    except DORAPIError as exc:
        raise ArtifactAcceptanceGUIError(
            f"Artifact acceptance blev afvist ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping) or response.get("command_id") != command_id:
        raise ArtifactAcceptanceGUIError("Artifact acceptance response matcher ikke command_id")
    payload = response.get("acceptance")
    if not isinstance(payload, Mapping):
        raise ArtifactAcceptanceGUIError("Backend returnerede ingen artifact acceptance")
    try:
        acceptance = parse_multi_spec_artifact_acceptance(payload)
    except ArtifactAcceptanceError as exc:
        raise ArtifactAcceptanceGUIError(str(exc)) from exc
    expected_ids = tuple(sorted(manifest_ids))
    actual_ids = tuple(item.manifest_id for item in acceptance.specs)
    if acceptance.organization_id != organization_id or actual_ids != expected_ids:
        raise ArtifactAcceptanceGUIError(
            "Artifact acceptance matcher ikke den valgte tenant/spec-bundle"
        )
    if not acceptance.authoritative or acceptance.release_authority:
        raise ArtifactAcceptanceGUIError("Artifact acceptance authority-scope er ugyldig")
    return {
        "command_id": command_id,
        "replayed": response.get("replayed") is True,
        "acceptance": acceptance.canonical(),
    }


def render_artifact_acceptance(client: DORAPIClient) -> None:
    """Render multi-spec selection and explicit human acceptance attestation."""
    st.subheader("Multi-Spec Verified Artifact Acceptance")
    st.caption(
        "COMPLETE traceability manifests → same PASS-certified artifact file-set → explicit admin acceptance"
    )

    organization_id = st.session_state.get("organization_id")
    if not isinstance(organization_id, str) or not organization_id:
        st.warning("Vælg en aktiv organisation først.")
        return

    repository: str | None = None
    current_result = st.session_state.get("requirement_traceability_result")
    if isinstance(current_result, Mapping) and isinstance(current_result.get("manifest"), Mapping):
        raw_repository = current_result["manifest"].get("repository")
        if isinstance(raw_repository, str) and raw_repository:
            repository = raw_repository

    try:
        catalog = load_eligible_manifest_catalog(
            client,
            organization_id=organization_id,
            repository=repository,
        )
    except ArtifactAcceptanceGUIError as exc:
        st.error(str(exc))
        return

    if len(catalog) < 2:
        st.warning(
            "Der findes endnu ikke mindst to COMPLETE traceability manifests"
            + (f" for {repository}." if repository else ".")
        )
        st.caption(
            "Kør Requirements → Plan → Delivery Certificate → Traceability for mindst to forskellige specs, som ender i samme artifact file-set."
        )
        st.page_link(
            "pages/08_Requirement_Artifact_Traceability.py",
            label="Tilbage til Requirement Traceability",
            icon="↩️",
        )
        return

    by_id = {item["manifest_id"]: item for item in catalog}
    options = list(by_id)

    def _label(manifest_id: str) -> str:
        item = by_id[manifest_id]
        return (
            f"{item['repository']} · plan {str(item['plan_id'])[:12]} · "
            f"manifest {manifest_id[:12]} · {item['requirement_count']} requirements"
        )

    selected = st.multiselect(
        "COMPLETE traceability specs",
        options=options,
        format_func=_label,
        key="artifact_acceptance_manifest_ids",
        help="Vælg mindst to forskellige specs. Backend kræver, at de alle resolve'r til samme PASS-certificerede artifact file-set.",
    )
    selected_ids = tuple(sorted(selected))
    distinct_plans = {
        str(by_id[item]["plan_request_fingerprint"])
        for item in selected_ids
        if item in by_id
    }

    cols = st.columns(3)
    cols[0].metric("Selected specs", len(selected_ids))
    cols[1].metric("Distinct plans", len(distinct_plans))
    cols[2].metric("Required", "≥ 2")

    if selected_ids:
        st.markdown("### Exact spec review")
        for manifest_id in selected_ids:
            try:
                manifest = load_traceability_manifest(
                    client,
                    organization_id=organization_id,
                    manifest_id=manifest_id,
                )
            except ArtifactAcceptanceGUIError as exc:
                st.error(str(exc))
                return
            with st.expander(
                f"Plan {str(manifest['plan_id'])[:12]} · manifest {manifest_id[:12]}",
                expanded=True,
            ):
                st.caption(
                    f"Certificate {str(manifest['certificate_id'])[:12]} · candidate {str(manifest['candidate_id'])[:12]}"
                )
                for requirement in manifest.get("requirements", []):
                    if isinstance(requirement, Mapping):
                        st.markdown(f"**{str(requirement.get('kind', 'requirement')).replace('_', ' ').title()}**")
                        st.write(requirement.get("text", ""))
                st.caption(
                    "Dette manifest er COMPLETE reference traceability; det er ikke machine semantic verification."
                )

    rationale = st.text_area(
        "Acceptance rationale (valgfrit)",
        max_chars=2_000,
        key="artifact_acceptance_rationale",
        help="Begrund den menneskelige accept af det eksakte multi-spec bundle.",
    ).strip()

    ready = len(selected_ids) >= 2 and len(distinct_plans) >= 2
    if len(selected_ids) >= 2 and len(distinct_plans) < 2:
        st.error("Multi-spec acceptance kræver mindst to forskellige plan request fingerprints.")

    try:
        draft = (
            acceptance_draft_fingerprint(
                organization_id=organization_id,
                manifest_ids=selected_ids,
                rationale=rationale,
            )
            if ready
            else None
        )
    except ArtifactAcceptanceGUIError as exc:
        st.error(str(exc))
        return
    command_id = _command_id(draft) if isinstance(draft, str) else ""

    st.warning(
        "ACCEPTED er human-authoritative inden for multi-spec artifact acceptance. "
        "Det er ikke en machine semantic PASS og giver ingen merge/release/deploy/execution authority."
    )
    confirmed = st.checkbox(
        "Jeg har gennemgået de eksakte COMPLETE manifests og accepterer det samme verificerede artifact-set for disse specs",
        key="artifact_acceptance_confirmed",
    )
    if st.button(
        "Acceptér exact multi-spec artifact bundle",
        type="primary",
        disabled=not (ready and confirmed),
    ):
        try:
            result = submit_artifact_acceptance(
                client,
                organization_id=organization_id,
                manifest_ids=selected_ids,
                rationale=rationale,
                command_id=command_id,
            )
            st.session_state["artifact_acceptance_result"] = result
            st.session_state["selected_artifact_acceptance_id"] = result["acceptance"][
                "acceptance_id"
            ]
        except ArtifactAcceptanceGUIError as exc:
            st.error(str(exc))

    result = st.session_state.get("artifact_acceptance_result")
    if isinstance(result, Mapping):
        payload = result.get("acceptance")
        if isinstance(payload, Mapping):
            try:
                acceptance = parse_multi_spec_artifact_acceptance(payload)
            except ArtifactAcceptanceError as exc:
                st.error(str(exc))
                return
            if tuple(item.manifest_id for item in acceptance.specs) == selected_ids:
                st.success(
                    "ACCEPTED — det eksakte verified artifact file-set er human-accepteret for det valgte multi-spec bundle."
                )
                st.info(
                    "machine_semantic_verification = null og release/deploy/merge/execution authority = false."
                )
                st.code(
                    json.dumps(
                        acceptance.canonical(),
                        indent=2,
                        sort_keys=True,
                        ensure_ascii=False,
                    ),
                    language="json",
                )
                if result.get("replayed") is True:
                    st.caption("Serveren returnerede den eksisterende immutable acceptance (replay).")

    st.page_link(
        "pages/08_Requirement_Artifact_Traceability.py",
        label="Tilbage til Requirement Traceability",
        icon="↩️",
    )


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = [
    "ArtifactAcceptanceGUIError",
    "acceptance_draft_fingerprint",
    "load_eligible_manifest_catalog",
    "load_traceability_manifest",
    "render_artifact_acceptance",
    "submit_artifact_acceptance",
]
