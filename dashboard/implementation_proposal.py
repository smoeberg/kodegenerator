"""Streamlit bridge from an immutable AI-6 plan to a governed patch proposal."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.project_planning import (
    ProjectPlanningGUIError,
    ProjectPlanningInput,
    planning_fingerprint,
    restore_planning_provenance,
)

_MAX_INSTRUCTION_CHARS = 8_000
_MAX_ALLOWED_PATHS = 8
_MAX_CHANGED_LINES = 1_000


class ImplementationProposalGUIError(RuntimeError):
    """The GUI cannot establish a safe exact implementation proposal request."""


@dataclass(frozen=True)
class ImplementationScope:
    """Human-declared exact repository scope and bounded change budget."""

    allowed_paths: tuple[str, ...]
    max_files: int = 1
    max_changed_lines: int = 100

    def __post_init__(self) -> None:
        paths = tuple(_validate_repository_path(path) for path in self.allowed_paths)
        if not paths:
            raise ValueError("Mindst én eksakt repository-fil skal være tilladt")
        if len(paths) != len(set(paths)):
            raise ValueError("Tilladte repository-paths skal være unikke")
        paths = tuple(sorted(paths))
        if len(paths) > _MAX_ALLOWED_PATHS:
            raise ValueError(f"Højst {_MAX_ALLOWED_PATHS} filer kan være i proposal-scope")
        if type(self.max_files) is not int or not 1 <= self.max_files <= _MAX_ALLOWED_PATHS:
            raise ValueError(f"max_files skal være mellem 1 og {_MAX_ALLOWED_PATHS}")
        if self.max_files > len(paths):
            raise ValueError("max_files kan ikke overstige antallet af eksplicit tilladte paths")
        if type(self.max_changed_lines) is not int or not 1 <= self.max_changed_lines <= _MAX_CHANGED_LINES:
            raise ValueError(
                f"max_changed_lines skal være mellem 1 og {_MAX_CHANGED_LINES}"
            )
        object.__setattr__(self, "allowed_paths", paths)

    def canonical(self) -> dict[str, Any]:
        return {
            "allowed_paths": list(self.allowed_paths),
            "max_files": self.max_files,
            "max_changed_lines": self.max_changed_lines,
        }


def restore_implementation_provenance(
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
) -> tuple[Any, ProjectPlanningInput, dict[str, str]]:
    """Revalidate the exact onboarding -> audit -> plan chain before proposal work."""
    try:
        intent, expected_provenance = restore_planning_provenance(
            onboarding_result,
            audit_result,
        )
    except ProjectPlanningGUIError as exc:
        raise ImplementationProposalGUIError(str(exc)) from exc

    if plan_result.get("status") != "proposed":
        raise ImplementationProposalGUIError("AI-6 planen skal være i proposed status")
    if plan_result.get("authoritative") is not False:
        raise ImplementationProposalGUIError("AI-6 planen må ikke gøre krav på authority")
    if plan_result.get("executable") is not False:
        raise ImplementationProposalGUIError("AI-6 planen må ikke være executable")
    if plan_result.get("resource") != intent.source_repository:
        raise ImplementationProposalGUIError(
            "AI-6 planens repository matcher ikke onboarding-intentet"
        )
    if plan_result.get("action") != intent.purpose.value:
        raise ImplementationProposalGUIError(
            "AI-6 planens action matcher ikke onboarding-intentets purpose"
        )

    raw_provenance = plan_result.get("provenance")
    if not isinstance(raw_provenance, Mapping) or dict(raw_provenance) != expected_provenance:
        raise ImplementationProposalGUIError(
            "AI-6 planens provenance matcher ikke det aktuelle Project Audit"
        )

    raw_requirements = plan_result.get("requirements")
    if not isinstance(raw_requirements, Mapping):
        raise ImplementationProposalGUIError("AI-6 planen mangler canonical requirements")
    try:
        requirements = ProjectPlanningInput(
            objective=str(raw_requirements["objective"]),
            acceptance_criteria=str(raw_requirements["acceptance_criteria"]),
            constraints=str(raw_requirements.get("constraints") or ""),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ImplementationProposalGUIError(
            "AI-6 planens requirements kan ikke gendannes canonical"
        ) from exc

    expected_request_fingerprint = planning_fingerprint(
        expected_provenance,
        requirements,
    )
    if plan_result.get("request_fingerprint") != expected_request_fingerprint:
        raise ImplementationProposalGUIError(
            "AI-6 planens request fingerprint matcher ikke requirements + audit provenance"
        )
    _verify_plan_content_identity(plan_result)
    return intent, requirements, expected_provenance


def default_implementation_instruction(plan_result: Mapping[str, Any]) -> str:
    """Render a bounded human-reviewable instruction from the proposed plan."""
    requirements = plan_result.get("requirements")
    if not isinstance(requirements, Mapping):
        raise ImplementationProposalGUIError("Planen mangler requirements")
    objective = str(requirements.get("objective") or "").strip()
    acceptance = str(requirements.get("acceptance_criteria") or "").strip()
    constraints = str(requirements.get("constraints") or "").strip()
    if not objective or not acceptance:
        raise ImplementationProposalGUIError("Planens requirements er ufuldstændige")

    lines = [
        "Propose a bounded text patch for the human-declared scope. Do not apply it.",
        f"Objective: {objective}",
        f"Acceptance criteria: {acceptance}",
    ]
    if constraints:
        lines.append(f"Constraints: {constraints}")
    steps = plan_result.get("steps")
    if isinstance(steps, list) and steps:
        lines.append("Plan steps:")
        for index, step in enumerate(steps[:16], start=1):
            text = str(step).strip()
            if text:
                lines.append(f"{index}. {text}")
    instruction = "\n".join(lines)
    if len(instruction) > _MAX_INSTRUCTION_CHARS:
        raise ImplementationProposalGUIError(
            f"Afledt implementation instruction overstiger {_MAX_INSTRUCTION_CHARS} tegn"
        )
    return instruction


def proposal_draft_fingerprint(
    *,
    plan_result: Mapping[str, Any],
    instruction: str,
    scope: ImplementationScope,
) -> str:
    """Content-address the user-visible request draft used for command idempotency."""
    canonical_instruction = _canonical_instruction(instruction)
    payload = {
        "schema_version": 1,
        "plan_id": _required_text(plan_result, "plan_id"),
        "plan_request_fingerprint": _required_text(plan_result, "request_fingerprint"),
        "instruction": canonical_instruction,
        "scope": scope.canonical(),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_proposal_payload(
    *,
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
    instruction: str,
    scope: ImplementationScope,
    command_id: str,
) -> dict[str, Any]:
    """Build the authenticated API command without granting or applying authority."""
    intent, requirements, provenance = restore_implementation_provenance(
        onboarding_result,
        audit_result,
        plan_result,
    )
    canonical_instruction = _canonical_instruction(instruction)
    if not command_id or command_id != command_id.strip():
        raise ImplementationProposalGUIError("command_id skal være canonical og ikke-tom")

    plan_context = {
        "plan_id": _required_text(plan_result, "plan_id"),
        "request_fingerprint": _required_text(plan_result, "request_fingerprint"),
        "action": _required_text(plan_result, "action"),
        "resource": _required_text(plan_result, "resource"),
        "steps": [str(step) for step in plan_result.get("steps", [])],
        "rationale": str(plan_result.get("rationale") or ""),
        "confidence": plan_result.get("confidence"),
    }
    context_provenance = f"plan:{plan_context['plan_id']}"
    return {
        "organization_id": intent.organization_id,
        "command_id": command_id,
        "resource": intent.source_repository,
        "instruction": canonical_instruction,
        "allowed_paths": list(scope.allowed_paths),
        "max_files": scope.max_files,
        "max_changed_lines": scope.max_changed_lines,
        "context_items": [
            {
                "source": "dor.project_planning",
                "key": "planning_provenance",
                "value": provenance,
                "relevance": 1.0,
                "provenance": context_provenance,
                "sensitivity": "normal",
            },
            {
                "source": "dor.project_planning",
                "key": "requirements",
                "value": requirements.canonical(),
                "relevance": 1.0,
                "provenance": context_provenance,
                "sensitivity": "normal",
            },
            {
                "source": "dor.project_planning",
                "key": "plan_proposal",
                "value": plan_context,
                "relevance": 1.0,
                "provenance": context_provenance,
                "sensitivity": "normal",
            },
        ],
    }


def submit_implementation_proposal(
    client: DORAPIClient,
    *,
    onboarding_result: Mapping[str, Any],
    audit_result: Mapping[str, Any],
    plan_result: Mapping[str, Any],
    instruction: str,
    scope: ImplementationScope,
    command_id: str,
) -> dict[str, Any]:
    """Submit exactly one bounded proposal command and verify the returned scope."""
    payload = build_proposal_payload(
        onboarding_result=onboarding_result,
        audit_result=audit_result,
        plan_result=plan_result,
        instruction=instruction,
        scope=scope,
        command_id=command_id,
    )
    try:
        response = client.post("/implementation-agent/proposals", json=payload)
    except DORAPIError as exc:
        raise ImplementationProposalGUIError(
            f"Implementation proposal blev afvist ({exc.status_code}): {exc}"
        ) from exc
    if not isinstance(response, Mapping):
        raise ImplementationProposalGUIError("Implementation API returnerede ikke et objekt")
    verified = _verify_proposal_response(response, payload, scope)
    return {
        "request": payload,
        "response": verified,
        "plan_id": _required_text(plan_result, "plan_id"),
        "plan_request_fingerprint": _required_text(plan_result, "request_fingerprint"),
        "authoritative": False,
        "applied": False,
    }


def render_implementation_proposal() -> None:
    """Render plan -> governed patch proposal without exposing patch execution."""
    st.subheader("Implementation Proposal")
    st.caption(
        "Onboarding → Project Audit → Requirements & Plan → governed patch proposal"
    )

    onboarding_result = st.session_state.get("onboarding_intent_result")
    audit_result = st.session_state.get("project_audit_result")
    plan_result = st.session_state.get("project_plan_result")
    if not all(
        isinstance(value, Mapping)
        for value in (onboarding_result, audit_result, plan_result)
    ):
        st.warning("Et valideret AI-6 planforslag er påkrævet før implementation proposal.")
        st.page_link(
            "pages/03_Requirements_And_Plan.py",
            label="Gå til Requirements & Plan",
            icon="↩️",
        )
        return

    try:
        intent, _, provenance = restore_implementation_provenance(
            onboarding_result,
            audit_result,
            plan_result,
        )
        default_instruction = default_implementation_instruction(plan_result)
    except ImplementationProposalGUIError as exc:
        st.error(str(exc))
        st.page_link(
            "pages/03_Requirements_And_Plan.py",
            label="Tilbage til Requirements & Plan",
            icon="↩️",
        )
        return

    cols = st.columns(4)
    cols[0].metric("Repository", intent.source_repository)
    cols[1].metric("Plan", str(plan_result["plan_id"])[:12])
    cols[2].metric("Audit", provenance["report_id"][:12])
    cols[3].metric("Commit", provenance["commit_sha"][:12])
    st.warning(
        "Dette trin må kun generere et patch-forslag. Patch-apply er en separat capability, "
        "authority-beslutning og execution-command og er ikke tilgængelig på denne side."
    )

    if "implementation_instruction" not in st.session_state:
        st.session_state["implementation_instruction"] = default_instruction
    instruction = st.text_area(
        "Implementation instruction",
        height=220,
        max_chars=_MAX_INSTRUCTION_CHARS,
        key="implementation_instruction",
        help="Instruktionen indgår i serverens content-addressed ImplementationRequest.",
    )
    allowed_text = st.text_area(
        "Eksakt tilladte repository-filer",
        height=140,
        key="implementation_allowed_paths",
        help="Én canonical repository-relative POSIX-fil pr. linje. Ingen directories, globs eller traversal.",
    )
    budget_cols = st.columns(2)
    max_files = int(
        budget_cols[0].number_input(
            "Max touched files",
            min_value=1,
            max_value=_MAX_ALLOWED_PATHS,
            value=1,
            step=1,
            key="implementation_max_files",
        )
    )
    max_changed_lines = int(
        budget_cols[1].number_input(
            "Max changed lines",
            min_value=1,
            max_value=_MAX_CHANGED_LINES,
            value=100,
            step=10,
            key="implementation_max_changed_lines",
        )
    )

    confirm = st.checkbox(
        "Jeg bekræfter den eksakte fil-scope og ønsker kun et patch-forslag — ikke patch-apply",
        key="implementation_proposal_confirmed",
    )

    try:
        paths = tuple(line.strip() for line in allowed_text.splitlines() if line.strip())
        scope = ImplementationScope(
            allowed_paths=paths,
            max_files=max_files,
            max_changed_lines=max_changed_lines,
        )
        draft_key = proposal_draft_fingerprint(
            plan_result=plan_result,
            instruction=instruction,
            scope=scope,
        )
        if st.session_state.get("_implementation_proposal_draft_key") != draft_key:
            st.session_state["_implementation_proposal_draft_key"] = draft_key
            st.session_state["_implementation_proposal_command_id"] = str(uuid.uuid4())
    except (ImplementationProposalGUIError, ValueError):
        scope = None
        draft_key = None

    if st.button("Generér governed patch-forslag", type="primary"):
        if not confirm:
            st.warning("Bekræft den eksakte proposal-scope først.")
        else:
            try:
                paths = tuple(
                    line.strip() for line in allowed_text.splitlines() if line.strip()
                )
                scope = ImplementationScope(
                    allowed_paths=paths,
                    max_files=max_files,
                    max_changed_lines=max_changed_lines,
                )
                current_draft = proposal_draft_fingerprint(
                    plan_result=plan_result,
                    instruction=instruction,
                    scope=scope,
                )
                if st.session_state.get("_implementation_proposal_draft_key") != current_draft:
                    st.session_state["_implementation_proposal_draft_key"] = current_draft
                    st.session_state["_implementation_proposal_command_id"] = str(uuid.uuid4())
                command_id = st.session_state["_implementation_proposal_command_id"]
                with st.spinner("Kører governed Implementation Agent proposal…"):
                    result = submit_implementation_proposal(
                        DORAPIClient(token=st.session_state.get("access_token")),
                        onboarding_result=onboarding_result,
                        audit_result=audit_result,
                        plan_result=plan_result,
                        instruction=instruction,
                        scope=scope,
                        command_id=command_id,
                    )
                st.session_state["implementation_proposal_result"] = result
                st.session_state["selected_implementation_proposal_id"] = result[
                    "response"
                ]["proposal"]["proposal_id"]
                st.success("Governed patch-forslag genereret. Ingen filer er anvendt.")
            except (ImplementationProposalGUIError, ValueError) as exc:
                st.error(str(exc))

    previous = st.session_state.get("implementation_proposal_result")
    if (
        isinstance(previous, Mapping)
        and previous.get("plan_id") == plan_result.get("plan_id")
        and previous.get("plan_request_fingerprint")
        == plan_result.get("request_fingerprint")
    ):
        _render_proposal(previous)

    st.page_link(
        "pages/03_Requirements_And_Plan.py",
        label="Tilbage til Requirements & Plan",
        icon="↩️",
    )


def _render_proposal(result: Mapping[str, Any]) -> None:
    response = result.get("response")
    if not isinstance(response, Mapping):
        return
    proposal = response.get("proposal")
    if not isinstance(proposal, Mapping):
        return
    st.markdown("### Patch-forslag")
    cols = st.columns(4)
    cols[0].metric("Authority", str(response.get("authority_decision", "—")))
    cols[1].metric("Execution", str(response.get("execution_status", "—")))
    cols[2].metric("Touched files", len(proposal.get("touched_paths", [])))
    cols[3].metric("Changed lines", proposal.get("changed_lines", "—"))
    if response.get("replayed"):
        st.info("Samme command blev replayed idempotent; provideren blev ikke kaldt igen.")
    st.success("Forslaget er valideret mod den eksplicitte file/change-budget scope.")
    st.code(str(proposal.get("unified_diff") or ""), language="diff")
    st.warning(
        "Forslaget er ikke anvendt. En fremtidig apply-operation skal bruge den separate "
        "implementation.apply_patch capability og en ny exact authority-bound baseline."
    )
    with st.expander("Teknisk proposal-provenance", expanded=False):
        st.json(result)


def _verify_plan_content_identity(plan_result: Mapping[str, Any]) -> None:
    try:
        steps_raw = plan_result["steps"]
        if not isinstance(steps_raw, list) or not steps_raw:
            raise TypeError("steps")
        steps = [str(step) for step in steps_raw]
        confidence = float(plan_result["confidence"])
        canonical = json.dumps(
            {
                "request_fingerprint": _required_text(
                    plan_result, "request_fingerprint"
                ),
                "resource": _required_text(plan_result, "resource"),
                "action": _required_text(plan_result, "action"),
                "steps": steps,
                "rationale": str(plan_result.get("rationale") or ""),
                "confidence": confidence,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ImplementationProposalGUIError(
            "AI-6 planens content identity kan ikke valideres"
        ) from exc
    expected_plan_id = f"plan-{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:16]}"
    if plan_result.get("plan_id") != expected_plan_id:
        raise ImplementationProposalGUIError(
            "AI-6 plan ID matcher ikke planens canonical output"
        )


def _verify_proposal_response(
    response: Mapping[str, Any],
    payload: Mapping[str, Any],
    scope: ImplementationScope,
) -> dict[str, Any]:
    if response.get("command_id") != payload.get("command_id"):
        raise ImplementationProposalGUIError("Proposal response matcher ikke command_id")
    if response.get("authority_decision") != "allow":
        raise ImplementationProposalGUIError("Proposal response mangler AI-3 ALLOW")
    if response.get("execution_status") not in {"succeeded", "replayed"}:
        raise ImplementationProposalGUIError("Proposal execution er ikke successful/replayed")
    if response.get("outcome_status") not in {"succeeded", "replayed"}:
        raise ImplementationProposalGUIError("Proposal outcome er ikke successful/replayed")
    proposal = response.get("proposal")
    if not isinstance(proposal, Mapping):
        raise ImplementationProposalGUIError("Proposal response mangler patch artifact")
    proposal_id = proposal.get("proposal_id")
    if not isinstance(proposal_id, str) or len(proposal_id) != 64:
        raise ImplementationProposalGUIError("Proposal ID er ikke canonical SHA-256")
    touched = proposal.get("touched_paths")
    if not isinstance(touched, list) or not touched:
        raise ImplementationProposalGUIError("Patch proposal mangler touched_paths")
    if any(path not in scope.allowed_paths for path in touched):
        raise ImplementationProposalGUIError("Patch proposal rører filer uden for approved scope")
    if len(touched) > scope.max_files:
        raise ImplementationProposalGUIError("Patch proposal overstiger approved file budget")
    changed_lines = proposal.get("changed_lines")
    if type(changed_lines) is not int or changed_lines < 1:
        raise ImplementationProposalGUIError("Patch proposal har ugyldigt changed_lines")
    if changed_lines > scope.max_changed_lines:
        raise ImplementationProposalGUIError("Patch proposal overstiger approved line budget")
    return dict(response)


def _validate_repository_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip() or path != path.strip():
        raise ValueError("Repository-paths skal være ikke-tomme canonical strings")
    if "\\" in path:
        raise ValueError("Repository-paths skal bruge POSIX '/' separator")
    candidate = PurePosixPath(path)
    if candidate.is_absolute() or path.startswith("/"):
        raise ValueError("Repository-paths skal være relative")
    if not candidate.parts or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("Repository-paths må ikke indeholde traversal-segmenter")
    if candidate.as_posix() != path:
        raise ValueError("Repository-paths skal være canonical POSIX paths")
    return path


def _canonical_instruction(value: str) -> str:
    if not isinstance(value, str):
        raise ImplementationProposalGUIError("instruction skal være tekst")
    value = value.strip()
    if not value:
        raise ImplementationProposalGUIError("instruction skal være ikke-tom")
    if len(value) > _MAX_INSTRUCTION_CHARS:
        raise ImplementationProposalGUIError(
            f"instruction må højst være {_MAX_INSTRUCTION_CHARS} tegn"
        )
    return value


def _required_text(source: Mapping[str, Any], key: str) -> str:
    value = source.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ImplementationProposalGUIError(f"Mangler canonical {key}")
    return value.strip()
