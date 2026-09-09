from __future__ import annotations

from dashboard.project_lifecycle import (
    build_archive_payload,
    build_cancel_payload,
    build_complete_payload,
    build_completion_request_payload,
    build_continue_payload,
    build_launch_payload,
    build_scope_activation_payload,
    lifecycle_affordances,
    lifecycle_error_message,
)


def _project(status: str, **overrides):
    project = {
        "project_id": "project-1",
        "organization_id": "org-1",
        "status": status,
        "revision": 7,
        "project_fingerprint": "1" * 64,
        "active_plan_request_fingerprint": "2" * 64,
        "archived_from_status": None,
    }
    project.update(overrides)
    return project


def test_lifecycle_affordances_follow_backend_reported_state_without_granting_authority():
    assert lifecycle_affordances(_project("created")) == ("launch",)
    assert lifecycle_affordances(_project("launch_requested")) == ("activate_scope",)
    assert lifecycle_affordances(_project("active")) == (
        "activate_scope",
        "request_completion",
        "cancel",
    )
    assert lifecycle_affordances(_project("completion_pending")) == (
        "complete",
        "cancel",
    )
    assert lifecycle_affordances(_project("completed")) == ("archive", "continue")
    assert lifecycle_affordances(_project("cancelled")) == ("archive",)
    assert lifecycle_affordances(
        _project("archived", archived_from_status="completed")
    ) == ("continue",)
    assert lifecycle_affordances(
        _project("archived", archived_from_status="cancelled")
    ) == ()


def test_mutation_payloads_bind_exact_server_snapshot_revision_and_plan():
    project = _project("active", revision=11)

    scope = build_scope_activation_payload(project, "org-1", "scope-cmd", "3" * 64)
    assert scope == {
        "organization_id": "org-1",
        "command_id": "scope-cmd",
        "plan_request_fingerprint": "3" * 64,
        "expected_revision": 11,
    }

    completion = build_completion_request_payload(project, "org-1", "complete-cmd")
    assert completion["expected_revision"] == 11
    assert completion["expected_plan_request_fingerprint"] == "2" * 64

    cancelled = build_cancel_payload(project, "org-1", "cancel-cmd", "obsolete")
    assert cancelled["expected_revision"] == 11
    assert cancelled["reason"] == "obsolete"

    archived = build_archive_payload(project, "org-1", "archive-cmd")
    assert archived["expected_revision"] == 11


def test_launch_payload_binds_immutable_project_fingerprint():
    payload = build_launch_payload(_project("created"), "org-1", "launch-cmd")
    assert payload == {
        "organization_id": "org-1",
        "command_id": "launch-cmd",
        "expected_project_fingerprint": "1" * 64,
    }


def test_complete_payload_carries_exact_evidence_and_current_plan_snapshot():
    project = _project("completion_pending", revision=13)
    evidence = {
        "onboarding_intent_id": "intent-1",
        "repository_commit_sha": "a" * 40,
        "delivery_certificate_id": "b" * 64,
        "traceability_manifest_id": "c" * 64,
        "integration_receipt_id": "d" * 64,
    }

    payload = build_complete_payload(project, "org-1", "finish-cmd", evidence)

    assert payload["expected_revision"] == 13
    assert payload["expected_plan_request_fingerprint"] == "2" * 64
    assert payload["evidence"] == evidence


def test_continuation_payload_uses_source_revision_and_new_intent_without_reopening_source():
    project = _project("completed", revision=21)
    intent = {
        "goal": "new goal",
        "description": "next scope",
        "priority": "high",
        "constraints": {"region": "eu"},
        "required_capabilities": ["repo.write"],
    }

    payload = build_continue_payload(
        project,
        "org-1",
        "continue-cmd",
        name="Next project",
        description="new lineage",
        intent=intent,
    )

    assert payload["expected_source_revision"] == 21
    assert payload["name"] == "Next project"
    assert payload["intent"] == intent
    assert "project_id" not in payload


def test_conflict_and_authorization_errors_preserve_backend_authority():
    level, message = lifecycle_error_message(409, "revision conflict")
    assert level == "warning"
    assert "Hent projektet igen" in message

    level, message = lifecycle_error_message(403, "authorization_denied")
    assert level == "error"
    assert "GUI'en kan ikke tilsidesætte" in message
