"""Streamlit bridge from a pending delivery handoff to authoritative certification."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from phase4.delivery_certificate import canonical_digest
from phase4.delivery_certification import (
    DELIVERY_CONTRACT_FINGERPRINT,
    DeliveryCandidateContractError,
    parse_delivery_verification_candidate,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class DeliveryCertificationGUIError(RuntimeError):
    """The dashboard cannot establish an exact authoritative certificate response."""


def _command_id(candidate_id: str) -> str:
    bound = st.session_state.get("_delivery_certification_candidate_id")
    command = st.session_state.get("_delivery_certification_command_id")
    if bound != candidate_id or not isinstance(command, str) or not command:
        command = str(uuid.uuid4())
        st.session_state["_delivery_certification_candidate_id"] = candidate_id
        st.session_state["_delivery_certification_command_id"] = command
    return command


def _verify_certificate_response(
    response: Mapping[str, Any],
    *,
    candidate_id: str,
    organization_id: str,
    command_id: str,
) -> dict[str, Any]:
    if response.get("command_id") != command_id:
        raise DeliveryCertificationGUIError("Certificate response matcher ikke command_id")
    certificate = response.get("certificate")
    if not isinstance(certificate, Mapping):
        raise DeliveryCertificationGUIError("Backend returnerede intet delivery certificate")
    canonical = dict(certificate)
    certificate_id = canonical.pop("certificate_id", None)
    if not isinstance(certificate_id, str) or not _HEX64.fullmatch(certificate_id):
        raise DeliveryCertificationGUIError("Delivery certificate ID er ugyldigt")
    if canonical_digest(canonical) != certificate_id:
        raise DeliveryCertificationGUIError(
            "Delivery certificate ID matcher ikke certificate content identity"
        )
    if canonical.get("schema_version") != 1:
        raise DeliveryCertificationGUIError("Ukendt delivery certificate schema")
    if canonical.get("candidate_id") != candidate_id:
        raise DeliveryCertificationGUIError("Certificate matcher ikke den valgte candidate")
    if canonical.get("organization_id") != organization_id:
        raise DeliveryCertificationGUIError("Certificate matcher ikke den aktive organisation")
    if canonical.get("contract_fingerprint") != DELIVERY_CONTRACT_FINGERPRINT:
        raise DeliveryCertificationGUIError("Certificate bruger ikke Delivery Contract v1")
    if canonical.get("authoritative") is not True:
        raise DeliveryCertificationGUIError("Certificate er ikke authoritative")
    result = canonical.get("result")
    reasons = canonical.get("reason_codes")
    if result not in {"pass", "fail"} or not isinstance(reasons, list) or not reasons:
        raise DeliveryCertificationGUIError("Certificate resultat/reasons er malformed")
    if result == "pass" and reasons != ["verified"]:
        raise DeliveryCertificationGUIError("PASS certificate har ugyldige reason codes")
    if result == "fail" and "verified" in reasons:
        raise DeliveryCertificationGUIError("FAIL certificate kan ikke være verified")
    canonical["certificate_id"] = certificate_id
    return canonical


def submit_delivery_certification(
    client: DORAPIClient,
    candidate_payload: Mapping[str, Any],
    *,
    organization_id: str,
    command_id: str,
) -> dict[str, Any]:
    try:
        candidate = parse_delivery_verification_candidate(candidate_payload)
    except DeliveryCandidateContractError as exc:
        raise DeliveryCertificationGUIError(str(exc)) from exc
    if candidate.organization_id != organization_id:
        raise DeliveryCertificationGUIError(
            "Delivery candidate matcher ikke den aktive organisation"
        )
    try:
        response = client.post(
            "/api/v1/control-plane/delivery-certificates",
            json={
                "command_id": command_id,
                "organization_id": organization_id,
                "candidate": candidate.canonical(),
            },
        )
    except DORAPIError as exc:
        raise DeliveryCertificationGUIError(
            f"Delivery certification blev afvist ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping):
        raise DeliveryCertificationGUIError("Delivery certification response er malformed")
    certificate = _verify_certificate_response(
        response,
        candidate_id=candidate.candidate_id,
        organization_id=organization_id,
        command_id=command_id,
    )
    return {
        "command_id": command_id,
        "replayed": response.get("replayed") is True,
        "certificate": certificate,
    }


def render_delivery_certification(client: DORAPIClient) -> None:
    """Render explicit authoritative verification without release/deploy side effects."""
    st.subheader("Authoritative Delivery Certificate")
    st.caption(
        "Pending handoff → server-owned apply provenance → trusted toolchain/workspace check → PASS/FAIL"
    )

    payload = st.session_state.get("delivery_verification_candidate")
    organization_id = st.session_state.get("organization_id")
    if not isinstance(payload, Mapping) or not isinstance(organization_id, str):
        st.warning("Opret først et Delivery Verification Handoff.")
        st.page_link(
            "pages/06_Delivery_Verification_Handoff.py",
            label="Gå til Delivery Verification Handoff",
            icon="↩️",
        )
        return
    try:
        candidate = parse_delivery_verification_candidate(payload)
    except DeliveryCandidateContractError as exc:
        st.error(f"Delivery candidate er ikke længere canonical: {exc}")
        return
    if candidate.organization_id != organization_id:
        st.error("Delivery candidate tilhører ikke den aktive organisation.")
        return

    cols = st.columns(4)
    cols[0].metric("Repository", candidate.repository)
    cols[1].metric("Candidate", candidate.candidate_id[:12])
    cols[2].metric("Apply record", candidate.apply_record_id[:12])
    cols[3].metric("Contract", "v1")
    st.warning(
        "Certificering er authoritative for Delivery Contract v1, men giver ingen "
        "release-, merge-, deploy- eller execution-authority."
    )
    st.caption(
        "Backend krydstjekker server-registreret apply request/record, artifact/evidence, "
        "trusted toolchain/executables og den aktuelle trusted workspace file-state."
    )

    command_id = _command_id(candidate.candidate_id)
    confirmed = st.checkbox(
        "Jeg vil evaluere denne eksakte candidate under Delivery Contract v1",
        key="delivery_certification_confirmed",
    )
    if st.button(
        "Kør authoritative delivery certification",
        type="primary",
        disabled=not confirmed,
    ):
        try:
            with st.spinner("Validerer server-owned delivery provenance…"):
                result = submit_delivery_certification(
                    client,
                    candidate.canonical(),
                    organization_id=organization_id,
                    command_id=command_id,
                )
            st.session_state["delivery_certificate_result"] = result
            st.session_state["selected_delivery_certificate_id"] = result["certificate"][
                "certificate_id"
            ]
        except DeliveryCertificationGUIError as exc:
            st.error(str(exc))

    result = st.session_state.get("delivery_certificate_result")
    if isinstance(result, Mapping):
        certificate = result.get("certificate")
        if isinstance(certificate, Mapping) and certificate.get("candidate_id") == candidate.candidate_id:
            verdict = certificate.get("result")
            if verdict == "pass":
                st.success("PASS — Delivery Contract v1 er authoritative verificeret.")
            elif verdict == "fail":
                st.error(
                    "FAIL — delivery candidate opfylder ikke Delivery Contract v1: "
                    + ", ".join(str(item) for item in certificate.get("reason_codes", []))
                )
            st.markdown("### Delivery certificate")
            st.code(
                json.dumps(certificate, indent=2, sort_keys=True, ensure_ascii=False),
                language="json",
            )
            if result.get("replayed") is True:
                st.caption("Serveren returnerede det eksisterende immutable certificate (replay).")
            st.info(
                "Næste release/deploy-trin er fortsat separat og er ikke aktiveret af dette certificate."
            )
            if verdict == "pass":
                st.page_link(
                    "pages/08_Requirement_Artifact_Traceability.py",
                    label="Fortsæt til Requirement → Artifact Traceability",
                    icon="🔗",
                )

    st.page_link(
        "pages/06_Delivery_Verification_Handoff.py",
        label="Tilbage til Delivery Verification Handoff",
        icon="↩️",
    )
