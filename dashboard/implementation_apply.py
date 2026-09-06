"""Streamlit bridge from a validated patch proposal to governed patch application."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.implementation_proposal import (
    ImplementationProposalGUIError,
    ImplementationScope,
    build_proposal_payload,
    restore_implementation_provenance,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_TOOL_KINDS = frozenset({"lint", "test", "build"})


class ImplementationApplyGUIError(RuntimeError):
    """The GUI cannot establish an exact governed patch-apply request."""


@dataclass(frozen=True)
class VerifiedPatchProposal:
    """Exact proposal identity revalidated from the current upstream session chain."""

    organization_id: str
    resource: str
    proposal_id: str
    proposal_request_fingerprint: str
    proposal_command_id: str
    provider_id: str
    diff_sha256: str
    touched_paths: tuple[str, ...]
    changed_lines: int
    unified_diff: str


def restore_apply_provenance(
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
    proposal_result: Mapping[str, Any],
) -> VerifiedPatchProposal:
    """Revalidate onboarding -> audit -> plan -> proposal before any mutation request."""
    try:
        intent, _, _ = restore_implementation_provenance(
            onboarding_result,
            audit_result,
            plan_result,
        )
    except ImplementationProposalGUIError as exc:
        raise ImplementationApplyGUIError(str(exc)) from exc

    if proposal_result.get("authoritative") is not False:
        raise ImplementationApplyGUIError(
            "Proposal-resultatet må ikke gøre krav på execution authority"
        )
    if proposal_result.get("applied") is not False:
        raise ImplementationApplyGUIError(
            "Proposal-resultatet skal være unapplied før governed apply"
        )
    if proposal_result.get("plan_id") != plan_result.get("plan_id"):
        raise ImplementationApplyGUIError("Proposal-resultatet matcher ikke den aktuelle AI-6 plan")
    if proposal_result.get("plan_request_fingerprint") != plan_result.get(
        "request_fingerprint"
    ):
        raise ImplementationApplyGUIError(
            "Proposal-resultatet matcher ikke planens request fingerprint"
        )

    request = proposal_result.get("request")
    response = proposal_result.get("response")
    if not isinstance(request, Mapping) or not isinstance(response, Mapping):
        raise ImplementationApplyGUIError(
            "Proposal-resultatet mangler canonical request/response provenance"
        )

    scope = _scope_from_request(request)
    command_id = _required_text(request, "command_id")
    instruction = _required_text(request, "instruction")
    try:
        expected_request = build_proposal_payload(
            onboarding_result=onboarding_result,
            audit_result=audit_result,
            plan_result=plan_result,
            instruction=instruction,
            scope=scope,
            command_id=command_id,
        )
    except (ImplementationProposalGUIError, ValueError) as exc:
        raise ImplementationApplyGUIError(str(exc)) from exc
    if dict(request) != expected_request:
        raise ImplementationApplyGUIError(
            "Proposal-requesten matcher ikke den aktuelle upstream provenance"
        )
    if request.get("organization_id") != intent.organization_id:
        raise ImplementationApplyGUIError("Proposal-requesten matcher ikke organisationen")
    if request.get("resource") != intent.source_repository:
        raise ImplementationApplyGUIError("Proposal-requesten matcher ikke repository resource")

    if response.get("command_id") != command_id:
        raise ImplementationApplyGUIError("Proposal response matcher ikke proposal command_id")
    if response.get("authority_decision") != "allow":
        raise ImplementationApplyGUIError("Proposal response mangler AI-3 ALLOW")
    if response.get("execution_status") not in {"succeeded", "replayed"}:
        raise ImplementationApplyGUIError("Proposal execution er ikke successful/replayed")
    if response.get("outcome_status") not in {"succeeded", "replayed"}:
        raise ImplementationApplyGUIError("Proposal outcome er ikke successful/replayed")

    request_fingerprint = _required_digest(response, "request_fingerprint")
    proposal = response.get("proposal")
    if not isinstance(proposal, Mapping):
        raise ImplementationApplyGUIError("Proposal response mangler patch artifact")

    proposal_id = _required_digest(proposal, "proposal_id")
    provider_id = _required_text(proposal, "provider_id")
    diff_sha256 = _required_digest(proposal, "diff_sha256")
    unified_diff = _required_text(proposal, "unified_diff")
    if hashlib.sha256(unified_diff.encode("utf-8")).hexdigest() != diff_sha256:
        raise ImplementationApplyGUIError("Patch diff SHA-256 matcher ikke unified diff")

    touched_raw = proposal.get("touched_paths")
    if not isinstance(touched_raw, list) or not touched_raw:
        raise ImplementationApplyGUIError("Patch proposal mangler touched_paths")
    touched_paths = tuple(str(path) for path in touched_raw)
    if len(touched_paths) != len(set(touched_paths)):
        raise ImplementationApplyGUIError("Patch proposal har dublerede touched_paths")
    if any(path not in scope.allowed_paths for path in touched_paths):
        raise ImplementationApplyGUIError("Patch proposal rører filer uden for approved scope")
    if len(touched_paths) > scope.max_files:
        raise ImplementationApplyGUIError("Patch proposal overstiger approved file budget")

    changed_lines = proposal.get("changed_lines")
    if type(changed_lines) is not int or not 1 <= changed_lines <= scope.max_changed_lines:
        raise ImplementationApplyGUIError("Patch proposal har ugyldigt changed-line budget")

    expected_proposal_id = _canonical_digest(
        {
            "request_fingerprint": request_fingerprint,
            "provider_id": provider_id,
            "diff_sha256": diff_sha256,
            "touched_paths": list(touched_paths),
            "changed_lines": changed_lines,
        }
    )
    if proposal_id != expected_proposal_id:
        raise ImplementationApplyGUIError(
            "Proposal ID matcher ikke proposalens canonical content identity"
        )

    return VerifiedPatchProposal(
        organization_id=intent.organization_id,
        resource=intent.source_repository,
        proposal_id=proposal_id,
        proposal_request_fingerprint=request_fingerprint,
        proposal_command_id=command_id,
        provider_id=provider_id,
        diff_sha256=diff_sha256,
        touched_paths=touched_paths,
        changed_lines=changed_lines,
        unified_diff=unified_diff,
    )


def build_apply_payload(
    proposal: VerifiedPatchProposal,
    *,
    command_id: str,
) -> dict[str, str]:
    """Build the minimal API command; baseline/toolchain stay server-owned."""
    if not isinstance(proposal, VerifiedPatchProposal):
        raise TypeError("proposal must be a VerifiedPatchProposal")
    if not command_id or command_id != command_id.strip():
        raise ImplementationApplyGUIError("apply command_id skal være canonical og ikke-tom")
    return {
        "organization_id": proposal.organization_id,
        "command_id": command_id,
        "proposal_id": proposal.proposal_id,
    }


def submit_governed_patch_apply(
    client: DORAPIClient,
    *,
    proposal: VerifiedPatchProposal,
    command_id: str,
) -> dict[str, Any]:
    """Submit one minimal patch-apply command and verify the immutable result."""
    payload = build_apply_payload(proposal, command_id=command_id)
    try:
        response = client.post("/implementation-agent/executions", json=payload)
    except DORAPIError as exc:
        raise ImplementationApplyGUIError(
            f"Governed patch apply blev afvist ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping):
        raise ImplementationApplyGUIError("Patch execution API returnerede ikke et objekt")
    verified = _verify_apply_response(response, payload, proposal)
    return {
        "request": payload,
        "response": verified,
        "proposal_id": proposal.proposal_id,
        "proposal_request_fingerprint": proposal.proposal_request_fingerprint,
        "applied": bool(verified["committed"]),
    }


def render_implementation_apply() -> None:
    """Render explicit human review followed by the existing governed apply command."""
    st.subheader("Patch Review & Apply")
    st.caption(
        "Onboarding → Project Audit → Requirements & Plan → Proposal → human review → governed apply"
    )

    onboarding_result = st.session_state.get("onboarding_intent_result")
    audit_result = st.session_state.get("project_audit_result")
    plan_result = st.session_state.get("project_plan_result")
    proposal_result = st.session_state.get("implementation_proposal_result")
    if not all(
        isinstance(value, Mapping)
        for value in (onboarding_result, audit_result, plan_result, proposal_result)
    ):
        st.warning("Et valideret patch-forslag er påkrævet før governed apply.")
        st.page_link(
            "pages/04_Implementation_Proposal.py",
            label="Gå til Implementation Proposal",
            icon="↩️",
        )
        return

    try:
        proposal = restore_apply_provenance(
            onboarding_result,
            audit_result,
            plan_result,
            proposal_result,
        )
    except ImplementationApplyGUIError as exc:
        st.error(str(exc))
        st.page_link(
            "pages/04_Implementation_Proposal.py",
            label="Tilbage til Implementation Proposal",
            icon="↩️",
        )
        return

    cols = st.columns(4)
    cols[0].metric("Repository", proposal.resource)
    cols[1].metric("Proposal", proposal.proposal_id[:12])
    cols[2].metric("Touched files", len(proposal.touched_paths))
    cols[3].metric("Changed lines", proposal.changed_lines)

    st.error(
        "Dette trin kan ændre den operator-konfigurerede workspace. Apply sker kun efter "
        "en ny human capability-check, en ny AI-3 authority-beslutning og serverens egne "
        "baseline-, lint-, test- og build-kontroller."
    )
    st.caption(
        "Browseren sender hverken filesystem-path, baseline, shell-kommandoer, toolchain "
        "eller hvilke checks der skal køres."
    )

    st.markdown("### Forslag til review")
    st.code(proposal.unified_diff, language="diff")
    st.markdown("**Eksakt touched scope**")
    for path in proposal.touched_paths:
        st.write(f"- `{path}`")

    previous = st.session_state.get("implementation_apply_result")
    if (
        isinstance(previous, Mapping)
        and previous.get("proposal_id") == proposal.proposal_id
        and isinstance(previous.get("response"), Mapping)
    ):
        _render_apply_result(previous)
        if previous.get("applied") is True:
            st.page_link(
                "pages/04_Implementation_Proposal.py",
                label="Tilbage til Implementation Proposal",
                icon="↩️",
            )
            return

    reviewed = st.checkbox(
        "Jeg har gennemgået det eksakte diff og touched scope",
        key="implementation_apply_reviewed",
    )
    confirmed = st.checkbox(
        "Jeg anmoder eksplicit om governed patch apply; serveren må stadig afvise operationen",
        key="implementation_apply_confirmed",
    )

    if st.session_state.get("_implementation_apply_proposal_id") != proposal.proposal_id:
        st.session_state["_implementation_apply_proposal_id"] = proposal.proposal_id
        st.session_state["_implementation_apply_command_id"] = str(uuid.uuid4())

    if st.button("Anmod om governed patch apply", type="primary"):
        if not reviewed or not confirmed:
            st.warning("Gennemgå diffet og bekræft apply-anmodningen først.")
        else:
            try:
                command_id = str(st.session_state["_implementation_apply_command_id"])
                with st.spinner(
                    "Observerer baseline, evaluerer authority og kører fixed lint/test/build…"
                ):
                    result = submit_governed_patch_apply(
                        DORAPIClient(token=st.session_state.get("access_token")),
                        proposal=proposal,
                        command_id=command_id,
                    )
                st.session_state["implementation_apply_result"] = result
                st.session_state["selected_implementation_patch_record_id"] = result[
                    "response"
                ]["record_id"]
                if result["applied"]:
                    st.success("Patch blev committed gennem den governed execution boundary.")
                else:
                    st.error("Patch blev ikke committed. Se execution-evidence nedenfor.")
            except ImplementationApplyGUIError as exc:
                st.error(str(exc))

    current = st.session_state.get("implementation_apply_result")
    if isinstance(current, Mapping) and current.get("proposal_id") == proposal.proposal_id:
        _render_apply_result(current)

    st.page_link(
        "pages/04_Implementation_Proposal.py",
        label="Tilbage til Implementation Proposal",
        icon="↩️",
    )


def _render_apply_result(result: Mapping[str, Any]) -> None:
    response = result.get("response")
    if not isinstance(response, Mapping):
        return
    st.markdown("### Governed apply-resultat")
    cols = st.columns(4)
    cols[0].metric("Authority", str(response.get("authority_decision", "—")))
    cols[1].metric("Record", str(response.get("record_status", "—")))
    cols[2].metric("Committed", "Ja" if response.get("committed") else "Nej")
    cols[3].metric("Rolled back", "Ja" if response.get("rolled_back") else "Nej")

    if response.get("committed"):
        st.success(
            "Serveren committed patchen efter exact baseline-binding og bestået fixed lint/test/build evidence."
        )
    else:
        st.error(
            "Serveren committed ikke patchen. En failure eller rollback giver ingen successful apply-status."
        )
        if response.get("error"):
            st.write(str(response["error"]))

    evidence = response.get("evidence")
    if isinstance(evidence, list) and evidence:
        rows = [
            {
                "tool": item.get("tool_id"),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "passed": item.get("passed"),
                "exit_code": item.get("exit_code"),
            }
            for item in evidence
            if isinstance(item, Mapping)
        ]
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)

    st.info(
        "Tool-evidence er ikke DOR PASS/FAIL authority. P3-20 forbliver den authoritative gate."
    )
    with st.expander("Teknisk patch-execution provenance", expanded=False):
        st.json(result)


def _scope_from_request(request: Mapping[str, Any]) -> ImplementationScope:
    paths = request.get("allowed_paths")
    if not isinstance(paths, list):
        raise ImplementationApplyGUIError("Proposal-requesten mangler allowed_paths")
    try:
        return ImplementationScope(
            allowed_paths=tuple(str(path) for path in paths),
            max_files=request.get("max_files"),
            max_changed_lines=request.get("max_changed_lines"),
        )
    except (TypeError, ValueError) as exc:
        raise ImplementationApplyGUIError("Proposal-requestens scope er ugyldig") from exc


def _verify_apply_response(
    response: Mapping[str, Any],
    payload: Mapping[str, Any],
    proposal: VerifiedPatchProposal,
) -> dict[str, Any]:
    if response.get("command_id") != payload.get("command_id"):
        raise ImplementationApplyGUIError("Patch execution response matcher ikke command_id")
    if response.get("proposal_id") != proposal.proposal_id:
        raise ImplementationApplyGUIError("Patch execution response matcher ikke proposal_id")
    if response.get("authority_decision") != "allow":
        raise ImplementationApplyGUIError("Patch execution response mangler AI-3 ALLOW")

    _required_digest(response, "request_fingerprint")
    baseline_fingerprint = _required_digest(response, "baseline_fingerprint")
    _required_digest(response, "toolchain_fingerprint")
    _required_digest(response, "record_id")

    record_status = response.get("record_status")
    if record_status not in {"succeeded", "failed"}:
        raise ImplementationApplyGUIError("Patch execution record har ukendt status")
    if type(response.get("committed")) is not bool or type(response.get("rolled_back")) is not bool:
        raise ImplementationApplyGUIError("Patch execution commit/rollback flags er ugyldige")

    committed = response["committed"]
    rolled_back = response["rolled_back"]
    error = response.get("error")
    evidence = response.get("evidence")
    if not isinstance(evidence, list):
        raise ImplementationApplyGUIError("Patch execution response mangler tool evidence")

    if record_status == "succeeded":
        if response.get("execution_status") not in {"succeeded", "replayed"}:
            raise ImplementationApplyGUIError("Successful patch record mangler successful AI-4 execution")
        if response.get("outcome_status") not in {"succeeded", "replayed"}:
            raise ImplementationApplyGUIError("Successful patch record mangler successful AI-5 outcome")
        if not committed or rolled_back or error is not None:
            raise ImplementationApplyGUIError("Successful patch record har inkonsistente commit-flags")
        artifact = response.get("artifact")
        if not isinstance(artifact, Mapping):
            raise ImplementationApplyGUIError("Successful patch record mangler committed artifact")
        _verify_apply_artifact(artifact, proposal, baseline_fingerprint)
        _verify_success_evidence(evidence, artifact)
    else:
        if committed:
            raise ImplementationApplyGUIError("Failed patch record må ikke være committed")
        if not isinstance(error, str) or not error.strip():
            raise ImplementationApplyGUIError("Failed patch record mangler non-empty error")

    return dict(response)


def _verify_apply_artifact(
    artifact: Mapping[str, Any],
    proposal: VerifiedPatchProposal,
    baseline_fingerprint: str,
) -> None:
    _required_digest(artifact, "artifact_id")
    if artifact.get("proposal_id") != proposal.proposal_id:
        raise ImplementationApplyGUIError("Patch artifact matcher ikke proposal_id")
    if artifact.get("diff_sha256") != proposal.diff_sha256:
        raise ImplementationApplyGUIError("Patch artifact matcher ikke proposal diff SHA-256")
    if artifact.get("baseline_fingerprint") != baseline_fingerprint:
        raise ImplementationApplyGUIError("Patch artifact matcher ikke authority-bound baseline")
    files = artifact.get("files")
    if not isinstance(files, list) or not files:
        raise ImplementationApplyGUIError("Patch artifact mangler file manifest")
    paths = tuple(str(item.get("path")) for item in files if isinstance(item, Mapping))
    if len(paths) != len(files) or tuple(sorted(paths)) != tuple(sorted(proposal.touched_paths)):
        raise ImplementationApplyGUIError("Patch artifact files matcher ikke proposal touched scope")


def _verify_success_evidence(
    evidence: list[Any],
    artifact: Mapping[str, Any],
) -> None:
    if not evidence:
        raise ImplementationApplyGUIError("Successful patch record mangler tool evidence")
    kinds: set[str] = set()
    for item in evidence:
        if not isinstance(item, Mapping):
            raise ImplementationApplyGUIError("Patch tool evidence er malformed")
        kind = item.get("kind")
        if kind not in _REQUIRED_TOOL_KINDS:
            raise ImplementationApplyGUIError("Patch tool evidence har ukendt tool kind")
        if kind in kinds:
            raise ImplementationApplyGUIError("Patch tool evidence har dubleret tool kind")
        kinds.add(str(kind))
        if item.get("status") != "passed" or item.get("passed") is not True:
            raise ImplementationApplyGUIError("Successful patch record indeholder ikke-passing evidence")
        if item.get("artifact_id") != artifact.get("artifact_id"):
            raise ImplementationApplyGUIError("Tool evidence matcher ikke committed artifact")
        _required_digest(item, "evidence_id")
        _required_digest(item, "tool_fingerprint")
    if kinds != _REQUIRED_TOOL_KINDS:
        raise ImplementationApplyGUIError("Successful patch record kræver lint, test og build evidence")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _required_digest(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ImplementationApplyGUIError(f"{key} er ikke canonical SHA-256")
    return value


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ImplementationApplyGUIError(f"Mangler canonical {key}")
    return value
