from datetime import datetime, timezone

import pytest

from domain.project import (
    Project,
    ProjectCompletionRecord,
    ProjectFingerprintError,
    ProjectIntent,
    ProjectStateError,
    ProjectStatus,
)


NOW = datetime(2026, 9, 8, 20, 0, tzinfo=timezone.utc)
PLAN = "1" * 64
COMMIT = "2" * 64
CERT = "3" * 64
TRACE = "4" * 64
INTEGRATION = "5" * 64


def active_project() -> Project:
    project = Project.create(
        project_id="project-1",
        organization_id="org-1",
        name="PC-101",
        description="lifecycle",
        intent=ProjectIntent(goal="ship lifecycle"),
        actor_id="owner",
        timestamp=NOW,
    )
    project = project.request_launch(
        actor_id="owner",
        command_id="launch-1",
        expected_project_fingerprint=project.fingerprint,
        timestamp=NOW,
    )
    return project.activate_scope(
        actor_id="owner",
        command_id="scope-1",
        plan_request_fingerprint=PLAN,
        expected_revision=project.revision,
        timestamp=NOW,
    )


def completion_record(project: Project) -> ProjectCompletionRecord:
    return ProjectCompletionRecord(
        organization_id=project.organization_id,
        project_id=project.id,
        final_project_revision=project.revision,
        onboarding_intent_id="intent-1",
        plan_request_fingerprint=PLAN,
        repository_commit_sha=COMMIT,
        delivery_certificate_ids=(CERT,),
        traceability_manifest_ids=(TRACE,),
        integration_evidence_ids=(INTEGRATION,),
        completed_by="owner",
        completed_at=NOW,
    )


def test_completion_pending_freezes_ordinary_work_and_binds_exact_plan() -> None:
    project = active_project()
    pending = project.request_completion(
        actor_id="owner",
        command_id="complete-request-1",
        expected_revision=project.revision,
        expected_plan_request_fingerprint=PLAN,
        timestamp=NOW,
    )

    assert pending.status is ProjectStatus.COMPLETION_PENDING
    assert pending.ordinary_work_allowed is False
    assert pending.active_plan_request_fingerprint == PLAN
    assert pending.revision == project.revision + 1

    with pytest.raises(ProjectStateError):
        pending.activate_scope(
            actor_id="owner",
            command_id="scope-2",
            plan_request_fingerprint="9" * 64,
            expected_revision=pending.revision,
            timestamp=NOW,
        )


def test_completion_rejects_stale_or_cross_scope_record() -> None:
    pending = active_project().request_completion(
        actor_id="owner",
        command_id="complete-request-1",
        expected_revision=2,
        expected_plan_request_fingerprint=PLAN,
        timestamp=NOW,
    )
    stale = ProjectCompletionRecord(
        organization_id=pending.organization_id,
        project_id=pending.id,
        final_project_revision=pending.revision,
        onboarding_intent_id="intent-1",
        plan_request_fingerprint="9" * 64,
        repository_commit_sha=COMMIT,
        delivery_certificate_ids=(CERT,),
        traceability_manifest_ids=(TRACE,),
        integration_evidence_ids=(INTEGRATION,),
        completed_by="owner",
        completed_at=NOW,
    )

    with pytest.raises(ProjectFingerprintError):
        pending.complete(record=stale, expected_revision=pending.revision)


def test_successful_completion_is_terminal_and_content_addressed() -> None:
    pending = active_project().request_completion(
        actor_id="owner",
        command_id="complete-request-1",
        expected_revision=2,
        expected_plan_request_fingerprint=PLAN,
        timestamp=NOW,
    )
    record = completion_record(pending)
    completed = pending.complete(record=record, expected_revision=pending.revision)

    assert completed.status is ProjectStatus.COMPLETED
    assert completed.completion_record_id == record.record_id
    assert completed.ordinary_work_allowed is False
    assert len(record.record_id) == 64

    with pytest.raises(ProjectStateError):
        completed.request_completion(
            actor_id="owner",
            command_id="again",
            expected_revision=completed.revision,
            expected_plan_request_fingerprint=PLAN,
            timestamp=NOW,
        )


def test_cancelled_project_never_has_completion_record() -> None:
    project = active_project()
    cancelled = project.cancel(
        actor_id="owner",
        command_id="cancel-1",
        reason="human owner stopped delivery",
        expected_revision=project.revision,
        timestamp=NOW,
    )

    assert cancelled.status is ProjectStatus.CANCELLED
    assert cancelled.completion_record_id is None
    assert cancelled.ordinary_work_allowed is False


def test_archive_preserves_terminal_truth() -> None:
    project = active_project().cancel(
        actor_id="owner",
        command_id="cancel-1",
        reason="stop",
        expected_revision=2,
        timestamp=NOW,
    )
    archived = project.archive(
        actor_id="owner",
        command_id="archive-1",
        expected_revision=project.revision,
        timestamp=NOW,
    )

    assert archived.status is ProjectStatus.ARCHIVED
    assert archived.archived_from_status is ProjectStatus.CANCELLED
    assert archived.cancel_command_id == "cancel-1"


def test_continuation_is_a_new_project_identity() -> None:
    original = active_project()
    continued = Project.create(
        project_id="project-2",
        organization_id=original.organization_id,
        name="Continuation",
        description="new lineage",
        intent=original.intent,
        actor_id="owner",
        timestamp=NOW,
        continued_from_project_id=original.id,
    )

    assert continued.id != original.id
    assert continued.continued_from_project_id == original.id
    assert continued.status is ProjectStatus.CREATED
