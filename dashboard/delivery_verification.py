"""Streamlit bridge from governed patch apply to a non-authoritative delivery handoff."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping

import streamlit as st

from dashboard.implementation_apply import (
    ImplementationApplyGUIError,
    restore_apply_provenance,
)
from phase4.delivery_certificate import (
    DeliveryArtifactFile,
    DeliveryVerificationCandidate,
    canonical_digest,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_TOOL_KINDS = frozenset({"lint", "test", "build"})


class DeliveryVerificationGUIError(RuntimeError):
    """A delivery handoff cannot establish exact successful-apply provenance."""


def build_delivery_verification_candidate(
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
    proposal_result: Mapping[str, Any],
    apply_result: Mapping[str, Any],
) -> DeliveryVerificationCandidate:
    """Revalidate the whole chain and content-address one pending delivery candidate."""
    try:
        proposal = restore_apply_provenance(
            onboarding_result,
            audit_result,
            plan_result,
            proposal_result,
        )
    except ImplementationApplyGUIError as exc:
        raise DeliveryVerificationGUIError(str(exc)) from exc

    if apply_result.get("proposal_id") != proposal.proposal_id:
        raise DeliveryVerificationGUIError(
            "Apply-resultatet matcher ikke det aktuelle patch proposal"
        )
    if apply_result.get("proposal_request_fingerprint") != proposal.proposal_request_fingerprint:
        raise DeliveryVerificationGUIError(
            "Apply-resultatet matcher ikke proposal request fingerprint"
        )
    if apply_result.get("applied") is not True:
        raise DeliveryVerificationGUIError(
            "Kun et successful committed apply kan blive delivery verification candidate"
        )

    request = apply_result.get("request")
    response = apply_result.get("response")
    if not isinstance(request, Mapping) or not isinstance(response, Mapping):
        raise DeliveryVerificationGUIError(
            "Apply-resultatet mangler canonical request/response provenance"
        )
    command_id = _required_text(request, "command_id")
    expected_request = {
        "organization_id": proposal.organization_id,
        "command_id": command_id,
        "proposal_id": proposal.proposal_id,
    }
    if dict(request) != expected_request:
        raise DeliveryVerificationGUIError(
            "Apply-requesten matcher ikke det validerede proposal og tenant scope"
        )

    if response.get("command_id") != command_id:
        raise DeliveryVerificationGUIError("Apply response matcher ikke command_id")
    if response.get("proposal_id") != proposal.proposal_id:
        raise DeliveryVerificationGUIError("Apply response matcher ikke proposal_id")
    if response.get("authority_decision") != "allow":
        raise DeliveryVerificationGUIError("Apply response mangler AI-3 ALLOW")
    if response.get("record_status") != "succeeded":
        raise DeliveryVerificationGUIError("Delivery candidate kræver successful patch record")
    if response.get("execution_status") not in {"succeeded", "replayed"}:
        raise DeliveryVerificationGUIError("Delivery candidate kræver successful AI-4 execution")
    if response.get("outcome_status") not in {"succeeded", "replayed"}:
        raise DeliveryVerificationGUIError("Delivery candidate kræver successful AI-5 outcome")
    if response.get("committed") is not True or response.get("rolled_back") is not False:
        raise DeliveryVerificationGUIError(
            "Delivery candidate kræver committed=true og rolled_back=false"
        )
    if response.get("error") is not None:
        raise DeliveryVerificationGUIError("Successful apply må ikke indeholde execution error")

    apply_request_fingerprint = _required_digest(response, "request_fingerprint")
    baseline_fingerprint = _required_digest(response, "baseline_fingerprint")
    toolchain_fingerprint = _required_digest(response, "toolchain_fingerprint")
    record_id = _required_digest(response, "record_id")

    artifact = response.get("artifact")
    if not isinstance(artifact, Mapping):
        raise DeliveryVerificationGUIError("Successful apply mangler committed artifact")
    artifact_id = _required_digest(artifact, "artifact_id")
    if artifact.get("proposal_id") != proposal.proposal_id:
        raise DeliveryVerificationGUIError("Committed artifact matcher ikke proposal_id")
    if artifact.get("diff_sha256") != proposal.diff_sha256:
        raise DeliveryVerificationGUIError("Committed artifact matcher ikke proposal diff")
    if artifact.get("baseline_fingerprint") != baseline_fingerprint:
        raise DeliveryVerificationGUIError("Committed artifact matcher ikke apply baseline")

    raw_files = artifact.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise DeliveryVerificationGUIError("Committed artifact mangler exact file manifest")
    try:
        files = tuple(
            DeliveryArtifactFile(
                path=_required_text(item, "path"),
                exists=item.get("exists"),
                sha256=item.get("sha256"),
                byte_count=item.get("byte_count"),
                mode=item.get("mode"),
            )
            for item in raw_files
            if isinstance(item, Mapping)
        )
    except (TypeError, ValueError) as exc:
        raise DeliveryVerificationGUIError("Committed artifact file manifest er ugyldigt") from exc
    if len(files) != len(raw_files):
        raise DeliveryVerificationGUIError("Committed artifact file manifest er malformed")
    if tuple(sorted(item.path for item in files)) != tuple(sorted(proposal.touched_paths)):
        raise DeliveryVerificationGUIError(
            "Committed artifact file manifest matcher ikke proposal touched scope"
        )
    expected_artifact_id = canonical_digest(
        {
            "proposal_id": proposal.proposal_id,
            "diff_sha256": proposal.diff_sha256,
            "baseline_fingerprint": baseline_fingerprint,
            "files": [item.canonical() for item in sorted(files, key=lambda item: item.path)],
        }
    )
    if artifact_id != expected_artifact_id:
        raise DeliveryVerificationGUIError(
            "Committed artifact ID matcher ikke artifactets canonical content identity"
        )

    raw_evidence = response.get("evidence")
    if not isinstance(raw_evidence, list) or len(raw_evidence) != 3:
        raise DeliveryVerificationGUIError(
            "Delivery candidate kræver præcis lint, test og build evidence"
        )
    evidence_ids: list[str] = []
    kinds: set[str] = set()
    for item in raw_evidence:
        if not isinstance(item, Mapping):
            raise DeliveryVerificationGUIError("Tool evidence er malformed")
        kind = item.get("kind")
        if kind not in _REQUIRED_TOOL_KINDS or kind in kinds:
            raise DeliveryVerificationGUIError("Tool evidence kinds er ugyldige eller dublerede")
        kinds.add(str(kind))
        if item.get("status") != "passed" or item.get("passed") is not True:
            raise DeliveryVerificationGUIError("Delivery candidate kræver passing tool evidence")
        if item.get("artifact_id") != artifact_id:
            raise DeliveryVerificationGUIError("Tool evidence matcher ikke committed artifact")
        evidence_ids.append(_verify_evidence_identity(item, artifact_id))
    if kinds != _REQUIRED_TOOL_KINDS:
        raise DeliveryVerificationGUIError("Delivery candidate kræver lint, test og build evidence")

    expected_record_id = canonical_digest(
        {
            "request_fingerprint": apply_request_fingerprint,
            "proposal_id": proposal.proposal_id,
            "baseline_fingerprint": baseline_fingerprint,
            "status": "succeeded",
            "artifact_id": artifact_id,
            "evidence_ids": evidence_ids,
            "committed": True,
            "rolled_back": False,
            "error": None,
        }
    )
    if record_id != expected_record_id:
        raise DeliveryVerificationGUIError(
            "Patch record ID matcher ikke apply-resultatets canonical content identity"
        )

    provenance = plan_result.get("provenance")
    if not isinstance(provenance, Mapping):
        raise DeliveryVerificationGUIError("AI-6 planen mangler audit provenance")
    try:
        return DeliveryVerificationCandidate(
            organization_id=proposal.organization_id,
            repository=proposal.resource,
            intent_id=_required_text(provenance, "intent_id"),
            onboarding_content_fingerprint=_required_digest(
                provenance, "content_fingerprint"
            ),
            audit_report_id=_required_digest(provenance, "report_id"),
            audit_request_fingerprint=_required_digest(
                provenance, "audit_request_fingerprint"
            ),
            audit_manifest_id=_required_digest(provenance, "manifest_id"),
            audit_evidence_bundle_id=_required_digest(
                provenance, "evidence_bundle_id"
            ),
            audit_commit_sha=_required_text(provenance, "commit_sha"),
            plan_id=_required_text(plan_result, "plan_id"),
            plan_request_fingerprint=_required_digest(
                plan_result, "request_fingerprint"
            ),
            proposal_id=proposal.proposal_id,
            proposal_request_fingerprint=proposal.proposal_request_fingerprint,
            apply_record_id=record_id,
            apply_request_fingerprint=apply_request_fingerprint,
            artifact_id=artifact_id,
            diff_sha256=proposal.diff_sha256,
            baseline_fingerprint=baseline_fingerprint,
            toolchain_fingerprint=toolchain_fingerprint,
            files=files,
            evidence_ids=tuple(evidence_ids),
        )
    except (TypeError, ValueError) as exc:
        raise DeliveryVerificationGUIError(str(exc)) from exc


def render_delivery_verification_handoff() -> None:
    """Render a pending, content-addressed handoff without claiming verification PASS."""
    st.subheader("Delivery Verification Handoff")
    st.caption(
        "Onboarding → Audit → Plan → Proposal → Apply → pending authoritative verification"
    )

    names = (
        "onboarding_intent_result",
        "project_audit_result",
        "project_plan_result",
        "implementation_proposal_result",
        "implementation_apply_result",
    )
    values = tuple(st.session_state.get(name) for name in names)
    if not all(isinstance(value, Mapping) for value in values):
        st.warning("Et successful governed patch apply er påkrævet før delivery handoff.")
        st.page_link(
            "pages/05_Patch_Review_And_Apply.py",
            label="Gå til Patch Review & Apply",
            icon="↩️",
        )
        return

    try:
        candidate = build_delivery_verification_candidate(*values)
    except DeliveryVerificationGUIError as exc:
        st.error(str(exc))
        st.page_link(
            "pages/05_Patch_Review_And_Apply.py",
            label="Tilbage til Patch Review & Apply",
            icon="↩️",
        )
        return

    cols = st.columns(4)
    cols[0].metric("Repository", candidate.repository)
    cols[1].metric("Candidate", candidate.candidate_id[:12])
    cols[2].metric("Apply record", candidate.apply_record_id[:12])
    cols[3].metric("Status", "PENDING")
    st.warning(
        "Dette er et provenance-handoff — ikke et delivery certificate med PASS. "
        "Kandidaten er eksplicit non-authoritative og har intet verification_result."
    )
    st.info(
        "Browseren starter ingen CI, shell-kommando, Git push, release eller deployment. "
        "En fremtidig authoritative gate skal konsumere candidate_id + provenance separat."
    )

    if st.button("Opret content-addressed verification handoff", type="primary"):
        canonical = candidate.canonical()
        st.session_state["delivery_verification_candidate"] = canonical
        st.session_state["selected_delivery_verification_candidate_id"] = candidate.candidate_id
        st.success("Verification handoff oprettet som PENDING. Ingen PASS/FAIL er udstedt.")

    previous = st.session_state.get("delivery_verification_candidate")
    if isinstance(previous, Mapping) and previous.get("candidate_id") == candidate.candidate_id:
        st.markdown("### Delivery candidate")
        st.code(
            json.dumps(previous, indent=2, sort_keys=True, ensure_ascii=False),
            language="json",
        )
        st.caption(
            "Candidate-ID'et er deterministisk over hele den validerede provenance-kæde, "
            "det committed artifact og de tre tool-evidence IDs."
        )

    st.page_link(
        "pages/05_Patch_Review_And_Apply.py",
        label="Tilbage til Patch Review & Apply",
        icon="↩️",
    )


def _verify_evidence_identity(item: Mapping[str, Any], artifact_id: str) -> str:
    evidence_id = _required_digest(item, "evidence_id")
    tool_fingerprint = _required_digest(item, "tool_fingerprint")
    stdout_id = _verify_log_identity(item.get("stdout"), "stdout")
    stderr_id = _verify_log_identity(item.get("stderr"), "stderr")
    expected = canonical_digest(
        {
            "tool_id": _required_text(item, "tool_id"),
            "kind": _required_text(item, "kind"),
            "tool_fingerprint": tool_fingerprint,
            "artifact_id": artifact_id,
            "status": _required_text(item, "status"),
            "exit_code": item.get("exit_code"),
            "stdout_artifact_id": stdout_id,
            "stderr_artifact_id": stderr_id,
        }
    )
    if evidence_id != expected:
        raise DeliveryVerificationGUIError(
            "Tool evidence ID matcher ikke evidence content identity"
        )
    return evidence_id


def _verify_log_identity(raw: object, stream: str) -> str:
    if not isinstance(raw, Mapping):
        raise DeliveryVerificationGUIError(f"{stream} evidence log er malformed")
    artifact_id = _required_digest(raw, "artifact_id")
    sha256 = _required_digest(raw, "sha256")
    byte_count = raw.get("byte_count")
    content = raw.get("content")
    truncated = raw.get("truncated")
    if type(byte_count) is not int or byte_count < 0:
        raise DeliveryVerificationGUIError(f"{stream} byte_count er ugyldig")
    if not isinstance(content, str) or type(truncated) is not bool:
        raise DeliveryVerificationGUIError(f"{stream} log metadata er ugyldig")
    if not truncated and hashlib.sha256(content.encode("utf-8")).hexdigest() != sha256:
        raise DeliveryVerificationGUIError(
            f"{stream} log SHA-256 matcher ikke det komplette logindhold"
        )
    expected = canonical_digest(
        {
            "stream": stream,
            "sha256": sha256,
            "byte_count": byte_count,
            "content": content,
            "truncated": truncated,
        }
    )
    if artifact_id != expected:
        raise DeliveryVerificationGUIError(
            f"{stream} log artifact ID matcher ikke log provenance"
        )
    return artifact_id


def _required_digest(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise DeliveryVerificationGUIError(f"{key} er ikke canonical SHA-256")
    return value


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise DeliveryVerificationGUIError(f"Mangler canonical {key}")
    return value
