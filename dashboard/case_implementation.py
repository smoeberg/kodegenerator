"""Case-bound execution start and governed Implementation Proposal surface.

This module continues an already audited/planned case into the canonical
software-factory pipeline. Project launch/scope activation, execution start and
proposal generation are all backend commands. The GUI never grants execution
authority and deliberately does not expose Patch Apply in this slice.
"""
from __future__ import annotations

import uuid
from collections.abc import Mapping, MutableMapping
from typing import Any

import streamlit as st
import yaml

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.case_audit_planning import (
    _AUDIT_CACHE_KEY,
    _PLAN_CACHE_KEY,
    _track_key,
    audit_matches_case,
    plan_matches_case,
    restore_case_intent,
)
from dashboard.case_workbench import CaseWorkbenchItem
from dashboard.implementation_proposal import (
    ImplementationProposalGUIError,
    ImplementationScope,
    build_proposal_payload,
    default_implementation_instruction,
    proposal_draft_fingerprint,
)
from dashboard.project_audit import ProjectAuditGUIError
from dashboard.project_lifecycle import (
    build_launch_payload,
    build_scope_activation_payload,
)
from dashboard.user_feedback import render_api_error
from phase4.onboarding import OnboardingIntent, OnboardingPurpose

_PROPOSAL_RESULTS_KEY = "case_implementation_proposals"
_PROPOSAL_COMMANDS_KEY = "case_implementation_proposal_commands"
_IMPLEMENTATION_STATES = frozenset({"code_generating", "code_generated"})
_TERMINAL_STATES = frozenset({"released", "failed", "cancelled"})


class CaseImplementationGUIError(RuntimeError):
    """The case surface cannot establish the exact governed implementation scope."""


def _cache(name: str) -> MutableMapping[str, Any]:
    value = st.session_state.get(name)
    if not isinstance(value, dict):
        value = {}
        st.session_state[name] = value
    return value


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CaseImplementationGUIError(f"Sagen mangler canonical {key}")
    return value.strip()


def _plan_fingerprint(plan: Mapping[str, Any]) -> str:
    value = _required_text(plan, "request_fingerprint")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CaseImplementationGUIError("Planens request fingerprint er ikke canonical SHA-256")
    return value


def plan_is_active(project: Mapping[str, Any], plan: Mapping[str, Any]) -> bool:
    """Read-only presentation hint; backend revalidates every mutation."""
    return (
        str(project.get("status") or "") == "active"
        and str(project.get("active_plan_request_fingerprint") or "")
        == _plan_fingerprint(plan)
    )


def requirements_yaml_for_execution(
    item: CaseWorkbenchItem,
    plan: Mapping[str, Any],
) -> str:
    """Build deterministic pipeline requirements from the exact case-bound plan."""
    requirements = plan.get("requirements")
    if not isinstance(requirements, Mapping):
        raise CaseImplementationGUIError("Planen mangler canonical requirements")
    objective = str(requirements.get("objective") or "").strip()
    acceptance = str(requirements.get("acceptance_criteria") or "").strip()
    constraints = str(requirements.get("constraints") or "").strip()
    if not objective or not acceptance:
        raise CaseImplementationGUIError("Planens objective og acceptkriterier skal være udfyldt")

    project_name = str(item.project.get("name") or item.projection.title).strip()
    description = str(item.project.get("description") or objective).strip()
    payload: dict[str, Any] = {
        "version": "1.0",
        "project_name": project_name,
        "project_description": description,
        "requirements": [
            {
                "id": "REQ-001",
                "description": objective,
                "acceptance_criteria": [acceptance],
            }
        ],
    }
    if constraints:
        payload["constraints"] = constraints
    return yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def _project_from_command(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise CaseImplementationGUIError("Backend returnerede ikke et project command-resultat")
    project = result.get("project")
    if not isinstance(project, Mapping):
        raise CaseImplementationGUIError("Backend-resultatet mangler project snapshot")
    return dict(project)


def activate_case_plan(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Request launch when needed and activate only the exact plan fingerprint."""
    project = dict(item.project)
    project_id = item.projection.case_id
    organization_id = _required_text(project, "organization_id")
    plan_request_fingerprint = _plan_fingerprint(plan)

    if plan_is_active(project, plan):
        return project

    status = str(project.get("status") or "")
    if status == "created":
        try:
            result = client.post(
                f"/api/v1/control-plane/projects/{project_id}/launch",
                json=build_launch_payload(project, organization_id, uuid.uuid4().hex),
            )
        except DORAPIError as exc:
            raise CaseImplementationGUIError(
                f"Backend afviste klargøring af sagen ({exc.status_code}): {exc}"
            ) from exc
        project = _project_from_command(result)
        status = str(project.get("status") or "")

    if status not in {"launch_requested", "active"}:
        raise CaseImplementationGUIError(
            f"Projektstatus {status or 'ukendt'} kan ikke aktivere et nyt arbejdsgrundlag"
        )

    try:
        result = client.post(
            f"/api/v1/control-plane/projects/{project_id}/scope/activate",
            json=build_scope_activation_payload(
                project,
                organization_id,
                uuid.uuid4().hex,
                plan_request_fingerprint,
            ),
        )
    except DORAPIError as exc:
        raise CaseImplementationGUIError(
            f"Backend afviste planens aktive scope ({exc.status_code}): {exc}"
        ) from exc

    activated = _project_from_command(result)
    if (
        str(activated.get("status") or "") != "active"
        or activated.get("active_plan_request_fingerprint") != plan_request_fingerprint
    ):
        raise CaseImplementationGUIError("Backend bekræftede ikke den eksakte plan som aktivt scope")
    return activated


def load_case_execution(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    plan: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Read the exact Project + active-plan execution from backend authority."""
    project_id = item.projection.case_id
    plan_fingerprint = _plan_fingerprint(plan)
    try:
        result = client.get(
            f"/api/v1/control-plane/projects/{project_id}/execution",
            params={"plan_request_fingerprint": plan_fingerprint},
        )
    except DORAPIError as exc:
        if exc.status_code == 404:
            return None
        raise CaseImplementationGUIError(
            f"Execution-status kunne ikke hentes ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(result, Mapping):
        raise CaseImplementationGUIError("Execution API returnerede ikke et canonical snapshot")
    if str(result.get("project_id") or "") != project_id:
        raise CaseImplementationGUIError("Execution snapshot matcher ikke den valgte Sag")
    if str(result.get("plan_request_fingerprint") or "") != plan_fingerprint:
        raise CaseImplementationGUIError("Execution snapshot matcher ikke den aktive plan")
    return dict(result)


def start_case_execution(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Start the canonical pipeline through the project-scoped backend boundary."""
    if not plan_is_active(item.project, plan):
        raise CaseImplementationGUIError("Planen er ikke sagens aktuelle aktive arbejdsgrundlag")
    project_id = item.projection.case_id
    plan_fingerprint = _plan_fingerprint(plan)
    try:
        result = client.post(
            f"/api/v1/control-plane/projects/{project_id}/execution",
            json={
                "requirements_yaml": requirements_yaml_for_execution(item, plan),
                "plan_request_fingerprint": plan_fingerprint,
            },
        )
    except DORAPIError as exc:
        raise CaseImplementationGUIError(
            f"Execution kunne ikke startes ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(result, Mapping) or not result.get("workflow_id"):
        raise CaseImplementationGUIError("Execution API returnerede ikke et canonical workflow")
    if result.get("project_id") != project_id or result.get("plan_request_fingerprint") != plan_fingerprint:
        raise CaseImplementationGUIError("Backend bekræftede ikke den eksakte Sag + plan binding")
    return dict(result)


def _verify_proposal_response(
    response: Mapping[str, Any],
    payload: Mapping[str, Any],
    scope: ImplementationScope,
) -> dict[str, Any]:
    if response.get("command_id") != payload.get("command_id"):
        raise CaseImplementationGUIError("Proposal response matcher ikke command_id")
    if response.get("authority_decision") != "allow":
        raise CaseImplementationGUIError("Proposal response mangler backend ALLOW")
    if response.get("execution_status") not in {"succeeded", "replayed"}:
        raise CaseImplementationGUIError("Proposal execution blev ikke gennemført")
    if response.get("outcome_status") not in {"succeeded", "replayed"}:
        raise CaseImplementationGUIError("Proposal outcome blev ikke gennemført")
    proposal = response.get("proposal")
    if not isinstance(proposal, Mapping):
        raise CaseImplementationGUIError("Proposal response mangler patch artifact")
    touched = proposal.get("touched_paths")
    if not isinstance(touched, list) or not touched:
        raise CaseImplementationGUIError("Patch proposal mangler touched_paths")
    if any(path not in scope.allowed_paths for path in touched):
        raise CaseImplementationGUIError("Patch proposal rører filer uden for bekræftet scope")
    if len(touched) > scope.max_files:
        raise CaseImplementationGUIError("Patch proposal overstiger bekræftet file budget")
    changed_lines = proposal.get("changed_lines")
    if type(changed_lines) is not int or not 1 <= changed_lines <= scope.max_changed_lines:
        raise CaseImplementationGUIError("Patch proposal overstiger bekræftet line budget")
    return dict(response)


def submit_case_implementation_proposal(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    *,
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
    instruction: str,
    scope: ImplementationScope,
    command_id: str,
) -> dict[str, Any]:
    """Submit a bounded proposal tied to active case scope; never apply it."""
    if not plan_is_active(item.project, plan_result):
        raise CaseImplementationGUIError("Implementation Proposal kræver sagens aktuelle aktive plan")
    payload = build_proposal_payload(
        onboarding_result=onboarding_result,
        audit_result=audit_result,
        plan_result=plan_result,
        instruction=instruction,
        scope=scope,
        command_id=command_id,
    )
    payload.update(
        {
            "project_id": item.projection.case_id,
            "plan_request_fingerprint": _plan_fingerprint(plan_result),
        }
    )
    if payload.get("organization_id") != item.project.get("organization_id"):
        raise CaseImplementationGUIError("Onboarding og Sag matcher ikke samme organisation")
    try:
        response = client.post("/implementation-agent/proposals", json=payload)
    except DORAPIError as exc:
        raise CaseImplementationGUIError(
            f"Implementation Proposal blev afvist ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping):
        raise CaseImplementationGUIError("Implementation API returnerede ikke et objekt")
    verified = _verify_proposal_response(response, payload, scope)
    return {
        "request": payload,
        "response": verified,
        "project_id": item.projection.case_id,
        "plan_id": _required_text(plan_result, "plan_id"),
        "plan_request_fingerprint": _plan_fingerprint(plan_result),
        "authoritative": False,
        "applied": False,
    }


def _render_proposal(result: Mapping[str, Any]) -> None:
    response = result.get("response")
    proposal = response.get("proposal") if isinstance(response, Mapping) else None
    if not isinstance(proposal, Mapping):
        return
    with st.container(border=True):
        st.markdown("**Patch-forslag**")
        cols = st.columns(2)
        cols[0].metric("Filer", len(proposal.get("touched_paths", [])))
        cols[1].metric("Ændrede linjer", proposal.get("changed_lines", "—"))
        st.code(str(proposal.get("unified_diff") or ""), language="diff")
        st.warning(
            "Forslaget er ikke anvendt. Patch Apply er en separat capability og er ikke en del af dette trin."
        )
        with st.expander("Teknisk proposal-provenance"):
            st.json(result)


def _render_proposal_form(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    intent_payload: Mapping[str, Any],
    audit: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    plan_fp = _plan_fingerprint(plan)
    key = f"{item.projection.case_id}:{plan_fp}"
    st.markdown("**Implementation Proposal**")
    st.caption(
        "Afgræns et patch-forslag til eksakte filer. Backend autoriserer proposal-kørslen; GUI'en kan ikke anvende patchen."
    )

    instruction = st.text_area(
        "Hvad skal implementationen foreslå?",
        value=default_implementation_instruction(plan),
        max_chars=8000,
        height=180,
        key=f"case-proposal-instruction-{key}",
    )
    allowed_text = st.text_area(
        "Eksakt tilladte filer",
        placeholder="dashboard/example.py\ntests/dashboard/test_example.py",
        key=f"case-proposal-paths-{key}",
        help="Én repository-relativ POSIX-fil pr. linje. Ingen globs eller directories.",
    )
    cols = st.columns(2)
    max_files = int(
        cols[0].number_input(
            "Maks. filer",
            min_value=1,
            max_value=8,
            value=1,
            key=f"case-proposal-files-{key}",
        )
    )
    max_changed_lines = int(
        cols[1].number_input(
            "Maks. ændrede linjer",
            min_value=1,
            max_value=1000,
            value=100,
            step=10,
            key=f"case-proposal-lines-{key}",
        )
    )
    confirm = st.checkbox(
        "Jeg bekræfter scope og ønsker kun et forslag — ikke Patch Apply",
        key=f"case-proposal-confirm-{key}",
    )

    if st.button(
        "Generér Implementation Proposal",
        type="primary",
        key=f"case-proposal-run-{key}",
        use_container_width=True,
    ):
        if not confirm:
            st.warning("Bekræft det eksakte proposal-scope først.")
        else:
            try:
                scope = ImplementationScope(
                    allowed_paths=tuple(
                        line.strip() for line in allowed_text.splitlines() if line.strip()
                    ),
                    max_files=max_files,
                    max_changed_lines=max_changed_lines,
                )
                draft = proposal_draft_fingerprint(
                    plan_result=plan,
                    instruction=instruction,
                    scope=scope,
                )
                command_id = str(
                    _cache(_PROPOSAL_COMMANDS_KEY).setdefault(draft, uuid.uuid4().hex)
                )
                result = submit_case_implementation_proposal(
                    client,
                    item,
                    onboarding_result={"intent": dict(intent_payload)},
                    audit_result=dict(audit),
                    plan_result=dict(plan),
                    instruction=instruction,
                    scope=scope,
                    command_id=command_id,
                )
                _cache(_PROPOSAL_RESULTS_KEY)[key] = result
            except (CaseImplementationGUIError, ImplementationProposalGUIError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success("Patch-forslaget er genereret. Ingen filer er anvendt.")
                st.rerun()

    previous = _cache(_PROPOSAL_RESULTS_KEY).get(key)
    if isinstance(previous, Mapping):
        _render_proposal(previous)


def _render_plan_track(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
    intent: OnboardingIntent,
    intent_payload: Mapping[str, Any],
    audit: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    project_id = item.projection.case_id
    plan_fp = _plan_fingerprint(plan)
    st.markdown(f"### Arbejde · {intent.source_repository}")

    if intent.purpose is OnboardingPurpose.AUDIT_ONLY:
        return

    if not plan_is_active(item.project, plan):
        status = str(item.project.get("status") or "")
        if status in {"completed", "completion_pending", "cancelled", "archived"}:
            st.info(
                "Sagens lifecycle-state tillader ikke, at dette planforslag bliver et nyt aktivt arbejdsgrundlag."
            )
            return
        if status == "active" and item.project.get("active_plan_request_fingerprint"):
            st.warning(
                "En anden plan er aktiv på sagen. Backend revaliderer scope, hvis du vælger denne plan."
            )
        st.write(
            "Planen er rådgivende, indtil du eksplicit gør den til sagens aktive arbejdsgrundlag."
        )
        if st.button(
            "Gør planen til aktivt arbejdsgrundlag",
            type="primary",
            key=f"case-activate-plan-{project_id}-{plan_fp}",
            use_container_width=True,
        ):
            try:
                activate_case_plan(client, item, plan)
            except CaseImplementationGUIError as exc:
                st.error(str(exc))
            else:
                st.success("Backend har aktiveret den eksakte plan for sagen.")
                st.rerun()
        return

    try:
        execution = load_case_execution(client, item, plan)
    except CaseImplementationGUIError as exc:
        st.error(str(exc))
        return

    if execution is None:
        st.write(
            "Det aktive arbejdsgrundlag er klar. Execution startes kun for denne Sag og denne eksakte plan."
        )
        if st.button(
            "Start arbejdet",
            type="primary",
            key=f"case-start-execution-{project_id}-{plan_fp}",
            use_container_width=True,
        ):
            try:
                start_case_execution(client, item, plan)
            except CaseImplementationGUIError as exc:
                st.error(str(exc))
            else:
                st.success("Execution er startet og bundet til sagen.")
                st.rerun()
        return

    state = str(execution.get("current_state") or "unknown").strip().lower()
    if state in _TERMINAL_STATES:
        st.caption("Denne plans execution er afsluttet. Se proces og evidens længere nede på sagen.")
        return

    st.caption(f"Execution er aktiv · {state}")
    if state in _IMPLEMENTATION_STATES:
        _render_proposal_form(client, item, intent_payload, audit, plan)
    else:
        st.info(
            "DOR fører execution gennem krav og løsningsdesign. Implementation Proposal bliver tilgængelig, når processen når implementering."
        )


def render_case_execution_implementation(
    client: DORAPIClient,
    item: CaseWorkbenchItem,
) -> None:
    """Continue current case plans into active execution and bounded proposals."""
    project_id = item.projection.case_id
    try:
        payload = client.get(
            "/api/v1/control-plane/onboarding-intents/current",
            params={"project_id": project_id},
        )
    except DORAPIError as exc:
        render_api_error(
            exc,
            key=f"case-implementation-intents-{project_id}",
            operation="Arbejdsgrundlaget kunne ikke hentes",
        )
        return
    intents = (
        [dict(value) for value in payload if isinstance(value, Mapping)]
        if isinstance(payload, list)
        else []
    )

    tracks: list[tuple[OnboardingIntent, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for intent_payload in intents:
        try:
            intent = restore_case_intent(intent_payload, project_id=project_id)
        except ProjectAuditGUIError:
            continue
        if intent.purpose is OnboardingPurpose.AUDIT_ONLY:
            continue
        audit_value = _cache(_AUDIT_CACHE_KEY).get(
            _track_key(project_id, intent.intent_id)
        )
        if not isinstance(audit_value, Mapping) or not audit_matches_case(
            audit_value,
            project_id=project_id,
            intent=intent,
        ):
            continue
        plan_value = _cache(_PLAN_CACHE_KEY).get(
            _track_key(project_id, intent.intent_id)
        )
        if not isinstance(plan_value, Mapping) or not plan_matches_case(
            plan_value,
            project_id=project_id,
            intent=intent,
            audit=audit_value,
        ):
            continue
        tracks.append((intent, intent_payload, dict(audit_value), dict(plan_value)))

    if not tracks:
        return

    st.write("")
    st.markdown("#### Execution og implementering")
    if len(tracks) > 1:
        st.info(
            "Sagen har flere planlagte repository-spor. Du vælger eksplicit, hvilket plan-scope der skal være aktivt; DOR vælger ikke for dig."
        )
    for index, (intent, intent_payload, audit, plan) in enumerate(tracks):
        _render_plan_track(client, item, intent, intent_payload, audit, plan)
        if index < len(tracks) - 1:
            st.divider()
