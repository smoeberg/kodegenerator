"""Tests for the AI-6 LLM planning service boundary."""

import pytest

from phase4.outcome.models import OutcomeRecord, OutcomeStatus
from phase4.planner import (
    DeterministicBaselinePlanner,
    GeneratedPlan,
    OpenAIPlannerProvider,
    PlannerService,
    PlanParseError,
)
from phase4.planner.models import PlanRequest, PlanStatus


def make_outcome(status: OutcomeStatus = OutcomeStatus.FAILED) -> OutcomeRecord:
    from datetime import datetime, timezone
    return OutcomeRecord(
        outcome_id="outcome-1",
        execution_id="exec-1",
        request_id="req-1",
        status=status,
        transitions=(),
        provenance_id="prov-1",
        produced_at=datetime.now(timezone.utc).isoformat(),
        error="boom",
    )


class _FakeProvider:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def generate_plan(self, prompt: str) -> dict:
        self.calls += 1
        return dict(self._payload)


def test_baseline_planner_derives_bounded_plan():
    service = PlannerService()
    plan = service.plan_from_spec(
        {"title": "Fix auth", "steps": ["add policy", "enforce", "test"]}
    )
    assert isinstance(plan, GeneratedPlan)
    assert plan.status is PlanStatus.PROPOSED
    assert plan.steps[0] == "add policy"
    assert plan.confidence == 0.5
    assert plan.plan_id.startswith("plan-")


def test_baseline_planner_caps_steps_and_requires_spec():
    service = PlannerService(max_steps=4)
    plan = service.plan_from_spec(
        {"title": "Big", "steps": [f"step {i}" for i in range(20)]}
    )
    assert len(plan.steps) == 4
    with pytest.raises(ValueError):
        service.plan_from_spec({})
    with pytest.raises(PlanParseError):
        DeterministicBaselinePlanner().generate_plan("not json")


def test_provider_payload_is_validated_and_bounded():
    service = PlannerService(provider=_FakeProvider({"resource": "r", "action": "a", "steps": ["s"], "rationale": "x", "confidence": 5.0}))
    plan = service.plan_from_spec({"title": "T"}, fingerprint="fp-1")
    assert plan.confidence == 1.0  # out-of-range confidence is clamped
    assert plan.request_fingerprint == "fp-1"


def test_provider_without_steps_rejected():
    service = PlannerService(provider=_FakeProvider({"resource": "r", "action": "a", "steps": []}))
    with pytest.raises(PlanParseError):
        service.plan_from_spec({"title": "T"})


def test_plan_from_request_returns_none_on_success():
    service = PlannerService()
    request = PlanRequest(
        outcome=make_outcome(OutcomeStatus.SUCCEEDED),
        resource="auth",
        action="implement",
        request_fingerprint="fp-2",
        context_packet_id="ctx-1",
    )
    assert service.plan_from_request(request) is None


def test_generated_plan_is_immutable_and_hashed():
    plan = PlannerService().plan_from_spec({"title": "T", "steps": ["s"]})
    with pytest.raises((AttributeError, TypeError)):
        plan.steps = ("other",)
    assert len(plan.plan_id) > 16
    assert plan.request_fingerprint


def test_openai_provider_requires_key():
    with pytest.raises(ValueError):
        OpenAIPlannerProvider(api_key="")
