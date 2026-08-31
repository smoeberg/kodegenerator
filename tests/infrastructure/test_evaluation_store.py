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
from phase4.verification.evaluation import EvaluationRubric, RubricCriterion


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
