"""Tests for the intelligent TaskRouter."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pytest

from services.task_router import (
    CAPABILITIES,
    DEFAULT_CAPABILITY,
    HumanApprovalGate,
    RouteDecision,
    TaskRouter,
)


@dataclass
class FakeTask:
    id: str
    title: str = ""
    description: str = ""
    wbs_phase: Optional[str] = None
    metadata: dict = field(default_factory=dict)


def test_routes_pure_api_task():
    router = TaskRouter()
    task = FakeTask(
        "t-api",
        title="Implement REST API endpoint for orders",
        description="Add OpenAPI-documented HTTP handlers for create order",
    )
    assert router.route(task) == "api"
    assert router.confidence(task) >= 0.55


def test_routes_pure_security_task():
    router = TaskRouter()
    task = FakeTask(
        "t-sec",
        title="Harden JWT authentication",
        description="Fix OAuth token validation and encryption of secrets",
        wbs_phase="security",
    )
    assert router.route(task) == "security"
    assert router.confidence(task) >= 0.55


def test_routes_pure_tests_task():
    router = TaskRouter()
    task = FakeTask(
        "t-test",
        title="Add unit tests for order service",
        description="Write pytest fixtures and coverage for edge cases",
        wbs_phase="testing",
    )
    assert router.route(task) == "tests"


def test_routes_pure_docs_task():
    router = TaskRouter()
    task = FakeTask(
        "t-docs",
        title="Update README documentation",
        description="Write a tutorial guide and changelog in markdown",
        wbs_phase="documentation",
    )
    assert router.route(task) == "docs"


def test_routes_domain_task():
    router = TaskRouter()
    task = FakeTask(
        "t-dom",
        title="Model the Order aggregate",
        description="Define domain entities, value objects and invariants",
        wbs_phase="architecture",
    )
    assert router.route(task) == "domain"


def test_ambiguous_task_selects_highest_score():
    router = TaskRouter(confidence_threshold=0.3)
    # Mix of service + api signals; score ranking must still pick a winner.
    task = FakeTask(
        "t-amb",
        title="Service adapter exposing API client",
        description="Build an integration service worker that calls a REST client",
    )
    decision = router.route_detailed(task)
    assert decision.capability in CAPABILITIES
    ranked = sorted(decision.scores.items(), key=lambda kv: (-kv[1], kv[0]))
    assert decision.capability == ranked[0][0]


def test_route_batch_matches_individual_and_is_deterministic():
    router = TaskRouter()
    tasks = [
        FakeTask("1", title="REST API endpoint", description="OpenAPI controller"),
        FakeTask("2", title="Security audit of auth", description="JWT and RBAC"),
        FakeTask("3", title="pytest unit tests", description="coverage fixtures"),
        FakeTask("4", title="README documentation", description="markdown guide"),
    ]
    batch = router.route_batch(tasks)
    individual = {t.id: router.route(t) for t in tasks}
    assert batch == individual
    # Second batch call is stable (cache + pure scoring).
    assert router.route_batch(tasks) == batch
    assert batch["1"] == "api"
    assert batch["2"] == "security"
    assert batch["3"] == "tests"
    assert batch["4"] == "docs"


def test_low_confidence_marked_for_human_review_via_gate():
    gate = HumanApprovalGate(confidence_threshold=0.55)
    router = TaskRouter(confidence_threshold=0.55, human_gate=gate)
    # Almost no signal → default capability with confidence 0.
    task = FakeTask("t-vague", title="Misc", description="stuff")
    decision = router.route_detailed(task)

    assert decision.capability == DEFAULT_CAPABILITY
    assert decision.confidence == 0.0
    assert decision.requires_human_review is True
    assert gate.evaluate(decision) == "HUMAN_REQUIRED"
    assert len(gate.pending_reviews) == 1
    review = gate.pending_reviews[0]
    assert review.task_id == "t-vague"
    assert review.requires_human() is True
    assert review.recommended_capability == DEFAULT_CAPABILITY


def test_high_confidence_is_autonomous():
    gate = HumanApprovalGate(confidence_threshold=0.5)
    router = TaskRouter(confidence_threshold=0.5, human_gate=gate)
    task = FakeTask(
        "t-clear",
        title="Write pytest unit tests",
        description="Add fixtures, mocks and coverage for the module",
        wbs_phase="testing",
    )
    decision = router.route_detailed(task)
    assert decision.capability == "tests"
    assert decision.confidence >= 0.5
    assert decision.requires_human_review is False
    assert gate.evaluate(decision) == "AUTONOMOUS"
    assert gate.pending_reviews == ()


def test_dict_task_supported():
    router = TaskRouter()
    task = {
        "task_id": "dict-1",
        "title": "API endpoint",
        "description": "REST handler",
        "wbs_phase": "implementation",
    }
    assert router.route(task) == "api"


def test_wbs_phase_prior_influences_routing():
    router = TaskRouter()
    # Weak docs signal, strong phase prior for documentation.
    task = FakeTask(
        "t-phase",
        title="Capture notes",
        description="Record decisions",
        wbs_phase="documentation",
    )
    assert router.route(task) == "docs"


def test_route_decision_to_dict():
    router = TaskRouter()
    task = FakeTask("t", title="API route", description="endpoint")
    d = router.route_detailed(task).to_dict()
    assert d["task_id"] == "t"
    assert d["capability"] == "api"
    assert 0.0 <= d["confidence"] <= 1.0
    assert set(d["scores"]) == set(CAPABILITIES)
