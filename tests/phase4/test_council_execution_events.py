"""Execution-to-Council event contract and idempotency tests."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.models import Base
from phase4.adaptation import AdaptationAction, ExecutionFailure, StrategyFingerprinter
from phase4.council import (
    CouncilEventBindingError,
    CouncilFailureEventHandler,
    CouncilRuntimeEventType,
    CouncilSessionBinding,
    CouncilStore,
    DeliberationSession,
    ExecutionFailedEvent,
    execution_failure_event_from_result,
)
from phase4.council.persistence_models import (
    CouncilFailureObservationModel,
    CouncilOutboxEventModel,
)
from phase4.epistemics import Hypothesis
from phase4.execution.models import ExecutionResult, ExecutionStatus


@pytest.fixture
def runtime():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    binding = CouncilSessionBinding(
        organization_id="org-1",
        context_packet_id="context-1",
        hypothesis_revision="hyp-rev-1",
        workspace_revision="git-rev-1",
    )
    session = DeliberationSession(
        Hypothesis(
            hypothesis_id="hyp-1",
            task_id="task-1",
            statement="Fix the failing authorization path",
        ),
        session_id="session-1",
    )
    CouncilStore(sessions).create(session, binding)
    return sessions, binding


def _failure_event(
    binding: CouncilSessionBinding,
    *,
    execution_id: str,
    workspace_revision: str | None = None,
) -> ExecutionFailedEvent:
    fingerprint = StrategyFingerprinter.create(
        hypothesis_id="hyp-1",
        affected_files=["api/auth.py"],
        change_pattern="tighten authorization check",
    )
    failure = ExecutionFailure(
        failure_id=execution_id,
        task_id="task-1",
        error_type="AssertionError",
        error_message="expected validation response",
        failed_tests=["test_authorization"],
    )
    return ExecutionFailedEvent.create(
        organization_id=binding.organization_id,
        session_id="session-1",
        hypothesis_id="hyp-1",
        hypothesis_revision=binding.hypothesis_revision,
        workspace_revision=workspace_revision or binding.workspace_revision,
        context_packet_id=binding.context_packet_id,
        execution_id=execution_id,
        fingerprint=fingerprint,
        failure=failure,
    )


def test_duplicate_delivery_is_idempotent_and_second_failure_requests_pivot(runtime):
    sessions, binding = runtime
    handler = CouncilFailureEventHandler(sessions)
    first = _failure_event(binding, execution_id="exec-1")

    result_1 = handler.handle(first)
    duplicate = CouncilFailureEventHandler(sessions).handle(first)
    result_2 = CouncilFailureEventHandler(sessions).handle(
        _failure_event(binding, execution_id="exec-2")
    )

    assert result_1.action is AdaptationAction.RETRY
    assert duplicate == result_1
    assert result_2.action is AdaptationAction.PIVOT_REQUEST
    assert result_2.pivot_required is True
    assert result_2.consecutive_same_failures == 2
    with sessions() as db:
        assert (
            db.scalar(select(func.count(CouncilFailureObservationModel.event_id))) == 2
        )
        types = db.scalars(
            select(CouncilOutboxEventModel.event_type).order_by(
                CouncilOutboxEventModel.created_at
            )
        ).all()
    assert types.count(CouncilRuntimeEventType.FAILURE_OBSERVED.value) == 1
    assert types.count(CouncilRuntimeEventType.PIVOT_REQUIRED.value) == 1


def test_mismatched_revision_is_rejected_without_observation(runtime):
    sessions, binding = runtime
    event = _failure_event(
        binding,
        execution_id="exec-stale",
        workspace_revision="stale-git-rev",
    )

    with pytest.raises(CouncilEventBindingError, match="provenance"):
        CouncilFailureEventHandler(sessions).handle(event)
    with sessions() as db:
        assert (
            db.scalar(select(func.count(CouncilFailureObservationModel.event_id))) == 0
        )


def test_failure_event_rejects_forged_digest(runtime):
    _, binding = runtime
    event = _failure_event(binding, execution_id="exec-1")
    forged = {**event.model_dump(), "event_id": "forged-event-id"}

    with pytest.raises(ValidationError, match="event digest is invalid"):
        ExecutionFailedEvent.model_validate(forged)


def test_execution_id_cannot_be_reused_with_changed_failure(runtime):
    sessions, binding = runtime
    original = _failure_event(binding, execution_id="exec-1")
    CouncilFailureEventHandler(sessions).handle(original)
    changed = ExecutionFailedEvent.create(
        organization_id=original.organization_id,
        session_id=original.session_id,
        hypothesis_id=original.hypothesis_id,
        hypothesis_revision=original.hypothesis_revision,
        workspace_revision=original.workspace_revision,
        context_packet_id=original.context_packet_id,
        execution_id=original.execution_id,
        fingerprint=original.fingerprint,
        failure=original.failure.model_copy(
            update={"error_message": "different failure content"}
        ),
    )

    with pytest.raises(CouncilEventBindingError, match="already observed"):
        CouncilFailureEventHandler(sessions).handle(changed)


@pytest.mark.parametrize(
    ("message", "expected_action", "expected_event_type"),
    [
        (
            "database connection failed: host is unreachable",
            AdaptationAction.HALT_ENVIRONMENT,
            CouncilRuntimeEventType.ENVIRONMENT_HALT_REQUIRED,
        ),
        (
            "security policy denied this operation",
            AdaptationAction.POLICY_ESCALATION,
            CouncilRuntimeEventType.POLICY_ESCALATION_REQUIRED,
        ),
    ],
)
def test_failure_actions_emit_explicit_runtime_events(
    runtime,
    message,
    expected_action,
    expected_event_type,
):
    sessions, binding = runtime
    event = _failure_event(binding, execution_id="exec-special")
    event = ExecutionFailedEvent.create(
        organization_id=event.organization_id,
        session_id=event.session_id,
        hypothesis_id=event.hypothesis_id,
        hypothesis_revision=event.hypothesis_revision,
        workspace_revision=event.workspace_revision,
        context_packet_id=event.context_packet_id,
        execution_id=event.execution_id,
        fingerprint=event.fingerprint,
        failure=event.failure.model_copy(update={"error_message": message}),
    )

    result = CouncilFailureEventHandler(sessions).handle(event)

    assert result.action is expected_action
    with sessions() as db:
        event_types = db.scalars(
            select(CouncilOutboxEventModel.event_type).where(
                CouncilOutboxEventModel.event_type == expected_event_type.value
            )
        ).all()
    assert event_types == [expected_event_type.value]


def test_execution_result_adapter_only_accepts_bound_failures(runtime):
    _, binding = runtime
    fingerprint = StrategyFingerprinter.create(
        hypothesis_id="hyp-1",
        affected_files=["service.py"],
        change_pattern="change service behavior",
    )
    result = ExecutionResult(
        execution_id="exec-1",
        request_id="request-1",
        authority_policy_id="policy-1",
        authority_policy_version="v1",
        agent_identity="agent-1",
        action="patch",
        resource="service.py",
        context_packet_id="context-1",
        status=ExecutionStatus.FAILED,
        adapter_id="sandbox",
        output=(),
        error="assertion failed",
        executed_at=datetime.now(timezone.utc).isoformat(),
    )

    event = execution_failure_event_from_result(
        result,
        binding=binding,
        session_id="session-1",
        hypothesis_id="hyp-1",
        fingerprint=fingerprint,
        task_id="task-1",
    )
    assert event.execution_id == result.execution_id
    assert event.failure.failure_id == result.execution_id

    succeeded = ExecutionResult(
        **{**result.__dict__, "status": ExecutionStatus.SUCCEEDED, "error": None}
    )
    with pytest.raises(ValueError, match="only FAILED"):
        execution_failure_event_from_result(
            succeeded,
            binding=binding,
            session_id="session-1",
            hypothesis_id="hyp-1",
            fingerprint=fingerprint,
            task_id="task-1",
        )
