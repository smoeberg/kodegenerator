"""Streamlit bootstrap and session-state helpers."""

from __future__ import annotations

import streamlit as st

from dashboard.api_client import DORAPIClient, DORAPIError
from dashboard.build_identity import current_build_identity


DEFAULTS = {
    "access_token": None,
    "username": None,
    "organization_id": None,
    "selected_project_id": None,
    "selected_project_fingerprint": None,
    "selected_workflow_id": None,
    "realtime_status": "offline",
}

_AUTH_SCOPED_ONBOARDING_KEYS = (
    "_artifact_acceptance_command_id",
    "_artifact_acceptance_draft_fingerprint",
    "_delivery_certification_candidate_id",
    "_delivery_certification_command_id",
    "_implementation_apply_command_id",
    "_implementation_apply_proposal_id",
    "_implementation_proposal_command_id",
    "_implementation_proposal_draft_key",
    "_onboarding_command_id",
    "_onboarding_command_draft_key",
    "_requirement_traceability_command_id",
    "_requirement_traceability_draft_fingerprint",
    "artifact_acceptance_confirmed",
    "artifact_acceptance_manifest_ids",
    "artifact_acceptance_rationale",
    "artifact_acceptance_result",
    "delivery_certificate_result",
    "delivery_certification_confirmed",
    "delivery_verification_candidate",
    "implementation_allowed_paths",
    "implementation_apply_confirmed",
    "implementation_apply_result",
    "implementation_apply_reviewed",
    "implementation_instruction",
    "implementation_max_changed_lines",
    "implementation_max_files",
    "implementation_proposal_confirmed",
    "implementation_proposal_result",
    "onboarding_delivery_allowed",
    "onboarding_intent_result",
    "onboarding_is_correction",
    "onboarding_purpose",
    "onboarding_rationale",
    "onboarding_ready_for_project_audit",
    "onboarding_source_repository",
    "onboarding_supersedes_intent_id",
    "onboarding_target_api",
    "onboarding_target_architecture",
    "onboarding_target_database",
    "onboarding_target_language",
    "onboarding_target_name",
    "project_audit_result",
    "project_plan_result",
    "project_planning_acceptance_criteria",
    "project_planning_constraints",
    "project_planning_objective",
    "requirement_traceability_confirmed",
    "requirement_traceability_result",
    "selected_artifact_acceptance_id",
    "selected_delivery_certificate_id",
    "selected_delivery_verification_candidate_id",
    "selected_implementation_patch_record_id",
    "selected_implementation_proposal_id",
    "selected_onboarding_intent_id",
    "selected_onboarding_repository",
    "selected_project_audit_report_id",
    "selected_project_plan_id",
    "selected_requirement_traceability_manifest_id",
)


def init_state() -> None:
    for key, value in DEFAULTS.items():
        st.session_state.setdefault(key, value)

    identity = current_build_identity()
    revision = identity.short_revision or "ukendt"
    st.sidebar.caption(
        f"DOR build `{identity.short_fingerprint}` · revision `{revision}`"
    )

    token = st.session_state.get("access_token")
    if token:
        # Bootstrap the accessible organization catalog from the authenticated
        # API. The selected organization remains GUI state; every backend call
        # still revalidates its runtime membership.
        from dashboard.context_navigation import (
            render_sidebar_organization_switcher,
            sync_organization_context,
        )

        client = DORAPIClient(token=token)
        try:
            sync_organization_context(client)
        except DORAPIError as exc:
            if exc.status_code == 401:
                clear_auth()
        except Exception:
            # Context navigation is a read-only convenience surface. Transport
            # failure must not suppress the existing API/cockpit paths.
            pass


def clear_auth() -> None:
    st.session_state["access_token"] = None
    st.session_state["username"] = None
    st.session_state["organization_id"] = None
    st.session_state["selected_project_id"] = None
    st.session_state["selected_project_fingerprint"] = None
    st.session_state["selected_workflow_id"] = None
    st.session_state.pop("workflow_input", None)
    st.session_state.pop("organization_context_catalog", None)
    st.session_state.pop("project_context_catalog", None)
    st.session_state.pop("active_organization_selector", None)
    for key in _AUTH_SCOPED_ONBOARDING_KEYS:
        st.session_state.pop(key, None)
    for key in tuple(st.session_state):
        if (
            key.startswith("artifact_acceptance_")
            or key.startswith("onboarding_target_api_")
            or key.startswith("onboarding_target_database_")
            or key.startswith("requirement_traceability_")
        ):
            st.session_state.pop(key, None)


def authenticated() -> bool:
    return bool(st.session_state.get("access_token"))
