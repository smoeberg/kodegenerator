from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from infrastructure.persistence.evaluation_models import EvaluationRubricModel
from infrastructure.persistence.evaluation_store import (
    EvaluationStore,
    EvaluationStoreConflictError,
)
from infrastructure.persistence.models import Base
from phase4.adaptation.performance import PerformanceObservation, PerformanceSnapshot
from phase4.council.configuration import IndependenceLevel
from phase4.verification.evaluation import (
    EvaluationAssignmentSnapshot,
    EvaluationCheck,
    EvaluationOutcome,
    EvaluationRecord,
    EvaluationRubric,
    RubricCriterion,
    evaluation_fingerprint,
)


def store():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return EvaluationStore(factory), factory


def value(organization_id: str = "org-1") -> EvaluationRubric:
    return EvaluationRubric(
        organization_id=organization_id,
        rubric_id="rubric-1",
        version=1,
        subject_classes=("candidate",),
        criteria=(RubricCriterion("tests", "Tests pass", 1.0, hard_failure=True),),
        pass_threshold=1.0,
        independence_level=IndependenceLevel.CONNECTION,
    )


def test_rubric_is_immutable_and_tenant_scoped() -> None:
    ledger, _ = store()
    ledger.add_rubric(value())
    loaded = ledger.get_rubric("org-1", "rubric-1", 1)
    assert loaded is not None and loaded.fingerprint == value().fingerprint
    assert ledger.get_rubric("org-2", "rubric-1", 1) is None
    with pytest.raises(EvaluationStoreConflictError):
        ledger.add_rubric(value())


def test_tampered_fingerprint_is_rejected_on_read() -> None:
    ledger, factory = store()
    ledger.add_rubric(value())
    with factory() as session, session.begin():
        row = session.get(EvaluationRubricModel, ("org-1", "rubric-1", 1))
        assert row is not None
        row.fingerprint = "0" * 64
    with pytest.raises(EvaluationStoreConflictError, match="fingerprint"):
        ledger.get_rubric("org-1", "rubric-1", 1)


def test_evaluation_round_trip_is_tenant_scoped() -> None:
    ledger, _ = store()
    assignment = EvaluationAssignmentSnapshot(
        assignment_id="a" * 64,
        bot_profile_id="profile-1",
        connection_id="connection-1",
        deployment_id="deployment-1",
        model_family="family-1",
        provider_adapter="adapter-1",
        brand="brand-1",
        prompt_version="v1",
    )
    values = {
        "organization_id": "org-1",
        "subject_id": "candidate-1",
        "subject_class": "candidate",
        "subject_fingerprint": "b" * 64,
        "rubric_id": "rubric-1",
        "rubric_version": 1,
        "rubric_fingerprint": "c" * 64,
        "base_sha": "d" * 40,
        "producer": assignment,
        "evaluator": None,
        "checks": (EvaluationCheck("tests", True, 1.0, ("test-attestation",)),),
        "semantic_evidence": (),
        "hard_failures": (),
        "outcome": EvaluationOutcome.PASS,
        "score": 1.0,
        "confidence": 1.0,
        "provenance": (("source", "deterministic"),),
    }
    record = EvaluationRecord(evaluation_id=evaluation_fingerprint(**values), **values)
    ledger.append_evaluation(record)

    assert ledger.get_evaluation("org-1", record.evaluation_id) == record
    assert ledger.get_evaluation("org-2", record.evaluation_id) is None


def test_observation_corrections_and_snapshot_ledger_boundary() -> None:
    ledger, _ = store()
    first = PerformanceObservation.create(
        organization_id="org-1",
        bot_profile_id="profile-1",
        role_id="reviewer",
        task_context="python",
        event_type="independent_review.passed",
        value=1.0,
        model_id="model-1",
        prompt_version="v1",
        rubric_id="rubric-1",
        evidence=("evaluation-1",),
        source="evaluation",
        ledger_position=1,
    )
    ledger.append_observation(first)
    correction = PerformanceObservation.create(
        organization_id="org-1",
        bot_profile_id="profile-1",
        role_id="reviewer",
        task_context="python",
        event_type="independent_review.passed",
        value=0.0,
        model_id="model-1",
        prompt_version="v1",
        rubric_id="rubric-1",
        evidence=("human-correction-1",),
        source="human",
        ledger_position=2,
        supersedes_observation_id=first.observation_id,
    )
    ledger.append_observation(correction)
    assert ledger.observations_through("org-1", 1) == (first,)
    now = datetime.now(timezone.utc)
    snapshot = PerformanceSnapshot.create(
        organization_id="org-1",
        bot_profile_id="profile-1",
        role_id="reviewer",
        task_context="python",
        sample_count=2,
        window_start=now,
        window_end=now,
        definitions=(("success_rate", "corrected event mean"),),
        values=(("success_rate", 0.0),),
        confidence=0.5,
        decay_version="v1",
        exclusions=(first.observation_id,),
        ledger_position=2,
    )
    ledger.add_snapshot(snapshot)
    assert ledger.get_snapshot("org-1", snapshot.snapshot_id) == snapshot
    assert ledger.get_snapshot("org-2", snapshot.snapshot_id) is None
