"""Governance, durability and replay tests for onboarding intent declaration."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain.actor import Actor, ActorType
from domain.authority import RoleAssignment, RoleDefinition
from domain.event import EventType
from domain.organization import Organization
from domain.principal import Principal
from generation.project_spec import ProjectDefinition
from infrastructure.persistence.command_repository import CommandRepository
from infrastructure.persistence.models import CommandExecutionModel, EventModel
from infrastructure.persistence.onboarding_intent_models import OnboardingIntentModel
from infrastructure.persistence.uow import UnitOfWork
from phase4.onboarding import OnboardingIntentDraft, OnboardingPurpose
from runtime.commands import CommandConflictError
from runtime.core import CommandAuthorizationError, DORRuntime
from runtime.onboarding_runtime import (
    ONBOARDING_INTENT_DECLARE_ACTION,
    DeclareOnboardingIntentCommand,
    OnboardingIntentConflictError,
    OnboardingIntentNotFoundError,
    OnboardingRuntime,
)


REPOSITORY = "repository:external/example"


def _runtime(tmp_path: Path) -> DORRuntime:
    runtime = DORRuntime(f"sqlite:///{tmp_path / 'onboarding.db'}")
    runtime.boot()
    for organization_id, actor_id in (("org-a", "actor-a"), ("org-b", "actor-b")):
        runtime.create_organization(Organization(id=organization_id, name=organization_id))
        runtime.register_actor(
            Actor(id=actor_id, type=ActorType.HUMAN, identity=actor_id),
            organization_id,
        )
    return runtime


def _context(
    runtime: DORRuntime,
    *,
    organization_id: str = "org-a",
    actor_id: str = "actor-a",
):
    return runtime.establish_context(
        Principal(id=actor_id, type="user", metadata={"actor_id": actor_id}),
        organization_id,
        actor_id,
    )


def _grant(
    runtime: DORRuntime,
    *,
    organization_id: str = "org-a",
    actor_id: str = "actor-a",
) -> None:
    role = RoleDefinition(
        id=f"onboarding.operator.{organization_id}",
        name="Onboarding Operator",
        organization_id=organization_id,
        capabilities=frozenset({ONBOARDING_INTENT_DECLARE_ACTION}),
    )
    assignment = RoleAssignment(
        actor_id=actor_id,
        organization_id=organization_id,
        role_definition_id=role.id,
        created_at=datetime.now(timezone.utc),
    )
    with runtime.database.session(organization_id) as session:
        with UnitOfWork(session) as uow:
            uow.authority.add_role_definition(role)
            uow.authority.assign_role(assignment)


def _draft(
    *,
    purpose: OnboardingPurpose = OnboardingPurpose.EXTEND,
    rationale: str = "Extend the existing repository without replacing its stack.",
    supersedes_intent_id: str | None = None,
) -> OnboardingIntentDraft:
    return OnboardingIntentDraft(
        source_repository=REPOSITORY,
        purpose=purpose,
        rationale=rationale,
        supersedes_intent_id=supersedes_intent_id,
    )


def _command(
    command_id: str = "onboarding-declare-1",
    *,
    organization_id: str = "org-a",
    draft: OnboardingIntentDraft | None = None,
) -> DeclareOnboardingIntentCommand:
    return DeclareOnboardingIntentCommand(
        command_id=command_id,
        organization_id=organization_id,
        draft=draft or _draft(),
    )


def _counts(runtime: DORRuntime, command_id: str) -> tuple[int, int, int]:
    with runtime.database.session() as session:
        intents = session.query(OnboardingIntentModel).count()
        receipts = (
            session.query(CommandExecutionModel)
            .filter_by(command_id=command_id)
            .count()
        )
        events = session.query(EventModel).filter_by(correlation_id=command_id).count()
    return intents, receipts, events


def test_declaration_fails_closed_without_external_capability_and_self_grants_nothing(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    command = _command()

    with pytest.raises(CommandAuthorizationError) as exc_info:
        OnboardingRuntime(runtime).declare_intent(_context(runtime), command)

    assert exc_info.value.decision.reason_code == "capability_not_granted"
    assert exc_info.value.decision.capability_id == ONBOARDING_INTENT_DECLARE_ACTION
    assert _counts(runtime, command.command_id) == (0, 0, 1)
    with runtime.database.session("org-a") as session:
        denial = session.query(EventModel).filter_by(correlation_id=command.command_id).one()
    assert denial.event_type == EventType.AUTHORIZATION_DENIED.name


def test_external_role_grant_records_trusted_actor_org_and_atomic_evidence(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    command = _command()

    result = OnboardingRuntime(runtime).declare_intent(_context(runtime), command)

    assert result.replayed is False
    assert result.intent.declared_by == "actor-a"
    assert result.intent.organization_id == "org-a"
    assert result.intent.source_repository == REPOSITORY
    assert result.intent.purpose is OnboardingPurpose.EXTEND
    assert _counts(runtime, command.command_id) == (1, 1, 2)

    with runtime.database.session("org-a") as session:
        rows = session.query(EventModel).filter_by(correlation_id=command.command_id).all()
        receipt = (
            session.query(CommandExecutionModel)
            .filter_by(command_id=command.command_id)
            .one()
        )
    assert {row.event_type for row in rows} == {
        EventType.AUTHORIZATION_GRANTED.name,
        EventType.INTENT_CREATED.name,
    }
    assert receipt.aggregate_id == result.intent.intent_id
    assert receipt.actor_id == "actor-a"
    assert receipt.organization_id == "org-a"


def test_exact_command_replay_survives_restart_without_new_events(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    command = _command()
    onboarding = OnboardingRuntime(runtime)
    context = _context(runtime)

    first = onboarding.declare_intent(context, command)
    second = onboarding.declare_intent(context, command)
    assert first.replayed is False
    assert second.replayed is True
    assert second.intent == first.intent
    assert _counts(runtime, command.command_id) == (1, 1, 2)

    restarted = DORRuntime(runtime.database_url)
    restarted.boot()
    after_restart = OnboardingRuntime(restarted).declare_intent(
        _context(restarted),
        command,
    )
    assert after_restart.replayed is True
    assert after_restart.intent.intent_id == first.intent.intent_id
    assert _counts(restarted, command.command_id) == (1, 1, 2)


def test_rewrite_target_stack_roundtrips_through_durable_persistence(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    target = ProjectDefinition(
        name="modernized-app",
        architecture="hexagonal",
        language="rust",
        api="axum",
        database="postgresql",
    )
    command = _command(
        "rewrite",
        draft=OnboardingIntentDraft(
            source_repository=REPOSITORY,
            purpose=OnboardingPurpose.MODERNIZE_REWRITE,
            rationale="Preserve behavior while moving to the explicit target stack.",
            target_stack=target,
        ),
    )

    first = OnboardingRuntime(runtime).declare_intent(_context(runtime), command)
    restarted = DORRuntime(runtime.database_url)
    restarted.boot()
    replay = OnboardingRuntime(restarted).declare_intent(_context(restarted), command)

    assert replay.replayed is True
    assert replay.intent.intent_id == first.intent.intent_id
    assert replay.intent.target_stack == target


def test_command_id_cannot_be_rebound_to_changed_semantics_or_tenant(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    _grant(runtime, organization_id="org-b", actor_id="actor-b")
    onboarding = OnboardingRuntime(runtime)
    onboarding.declare_intent(_context(runtime), _command())

    with pytest.raises(CommandConflictError):
        onboarding.declare_intent(
            _context(runtime),
            _command(draft=_draft(rationale="A different semantic declaration.")),
        )

    with pytest.raises(CommandConflictError):
        onboarding.declare_intent(
            _context(runtime, organization_id="org-b", actor_id="actor-b"),
            _command(organization_id="org-b"),
        )
    with runtime.database.session("org-b") as session:
        assert (
            session.query(OnboardingIntentModel)
            .filter_by(organization_id="org-b")
            .count()
            == 0
        )


def test_command_organization_mismatch_is_denied_before_state_mutation(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    command = _command(organization_id="org-b")

    with pytest.raises(CommandAuthorizationError) as exc_info:
        OnboardingRuntime(runtime).declare_intent(_context(runtime), command)

    assert exc_info.value.decision.reason_code == "command_organization_mismatch"
    assert _counts(runtime, command.command_id) == (0, 0, 1)


def test_supersession_requires_existing_same_repository_and_changed_semantics(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    onboarding = OnboardingRuntime(runtime)
    context = _context(runtime)

    with pytest.raises(OnboardingIntentNotFoundError):
        onboarding.declare_intent(
            context,
            _command(
                "missing-prior",
                draft=_draft(
                    rationale="Changed intent.",
                    supersedes_intent_id="a" * 64,
                ),
            ),
        )

    root = onboarding.declare_intent(context, _command("root")).intent
    with pytest.raises(OnboardingIntentConflictError, match="semantic"):
        onboarding.declare_intent(
            context,
            _command(
                "same-semantics",
                draft=_draft(supersedes_intent_id=root.intent_id),
            ),
        )

    other_repository = OnboardingIntentDraft(
        source_repository="repository:external/other",
        purpose=OnboardingPurpose.AUDIT_ONLY,
        rationale="Audit a different repository.",
        supersedes_intent_id=root.intent_id,
    )
    with pytest.raises(OnboardingIntentConflictError, match="same source repository"):
        onboarding.declare_intent(
            context,
            _command("different-repository", draft=other_repository),
        )


def test_supersession_is_linear_and_second_root_is_rejected(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    onboarding = OnboardingRuntime(runtime)
    context = _context(runtime)

    root = onboarding.declare_intent(context, _command("root")).intent
    successor = onboarding.declare_intent(
        context,
        _command(
            "successor",
            draft=_draft(
                purpose=OnboardingPurpose.AUDIT_ONLY,
                rationale="Audit before deciding how to continue.",
                supersedes_intent_id=root.intent_id,
            ),
        ),
    ).intent
    assert successor.supersedes_intent_id == root.intent_id

    with pytest.raises(OnboardingIntentConflictError, match="already has a successor"):
        onboarding.declare_intent(
            context,
            _command(
                "branch",
                draft=_draft(
                    rationale="Attempt to branch immutable history.",
                    supersedes_intent_id=root.intent_id,
                ),
            ),
        )

    with pytest.raises(OnboardingIntentConflictError, match="root intent"):
        onboarding.declare_intent(
            context,
            _command(
                "second-root",
                draft=_draft(rationale="Unlinked replacement root."),
            ),
        )


def test_cross_tenant_supersession_cannot_observe_or_link_foreign_intent(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    _grant(runtime, organization_id="org-b", actor_id="actor-b")
    onboarding = OnboardingRuntime(runtime)
    root = onboarding.declare_intent(
        _context(runtime),
        _command("org-a-root"),
    ).intent

    org_b_command = _command(
        "org-b-successor",
        organization_id="org-b",
        draft=_draft(
            rationale="Try to link a foreign tenant intent.",
            supersedes_intent_id=root.intent_id,
        ),
    )
    with pytest.raises(OnboardingIntentNotFoundError):
        onboarding.declare_intent(
            _context(runtime, organization_id="org-b", actor_id="actor-b"),
            org_b_command,
        )

    with runtime.database.session("org-b") as session:
        assert (
            session.query(OnboardingIntentModel)
            .filter_by(organization_id="org-b")
            .count()
            == 0
        )


def test_equivalent_intent_under_new_command_is_not_duplicated(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    onboarding = OnboardingRuntime(runtime)
    context = _context(runtime)
    onboarding.declare_intent(context, _command("first"))

    with pytest.raises(OnboardingIntentConflictError):
        onboarding.declare_intent(context, _command("second"))

    with runtime.database.session("org-a") as session:
        assert session.query(OnboardingIntentModel).count() == 1
        assert session.query(CommandExecutionModel).count() == 1


def test_receipt_failure_rolls_back_intent_and_granted_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = _runtime(tmp_path)
    _grant(runtime)
    command = _command("receipt-failure")

    def fail_receipt(*args, **kwargs):
        raise RuntimeError("simulated command receipt failure")

    monkeypatch.setattr(CommandRepository, "add", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt failure"):
        OnboardingRuntime(runtime).declare_intent(_context(runtime), command)

    assert _counts(runtime, command.command_id) == (0, 0, 0)
