"""Test dynamic requirement ingestion, parsing, Gherkin support, and compilation."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from domain.requirements import (
    AcceptanceCriterion,
    Requirement,
    RequirementsSpecification,
)
from generation.requirement_analysis import (
    analyze_requirements,
    parse_gherkin_scenarios,
    ingest_unstructured_requirements,
)
from services.task_compiler import TaskCompiler


def test_parse_gherkin_scenarios():
    text = """
    Feature: User Authentication
      Scenario: Successful login with valid credentials
        Given a registered user with email "user@example.com"
        When the user submits valid credentials
        Then the response code is 200
        And a JWT token is returned

      Scenario: Failed login with invalid password
        Given a registered user
        When the user submits wrong password
        Then the response code is 401
    """
    scenarios = parse_gherkin_scenarios(text)
    assert len(scenarios) == 2
    assert scenarios[0].title == "Successful login with valid credentials"
    assert "Given a registered user with email" in scenarios[0].steps[0]
    assert scenarios[1].title == "Failed login with invalid password"
    assert len(scenarios[1].steps) == 3


def test_ingest_unstructured_requirements_markdown():
    doc = """
    # Project: Payment Gateway

    ## Overview
    This project handles payment transactions securely.

    ## Requirements
    ### REQ-001: Process Credit Card
    Must process credit card payments via Stripe.
    Target: payments/service.py
    - Given valid card details, when charged, returns 200.
    - Given invalid card number, when charged, returns 400.

    ### REQ-002: Refund Transaction
    Should refund existing settled charges.
    Target: payments/refunds.py
    - When refund requested with valid charge_id, returns 200.
    """
    analysis = ingest_unstructured_requirements(doc, project_name="payment-gateway")
    assert analysis.project_name == "payment-gateway"
    assert len(analysis.requirements) == 2
    req1 = analysis.requirements[0]
    assert req1.id == "REQ-001"
    assert len(req1.acceptance_criteria) == 2
    assert req1.target_module == "payments/service.py"

    req2 = analysis.requirements[1]
    assert req2.id == "REQ-002"
    assert req2.target_module == "payments/refunds.py"


def test_task_compiler_integration_with_ingested_requirement():
    doc = """
    ### REQ-100: Health Check Endpoint
    Provide health status check.
    Target: api/health.py
    - GET /health returns 200 OK
    """
    analysis = ingest_unstructured_requirements(doc, project_name="health-api")
    req = analysis.requirements[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        repo = Path(tmpdir)
        (repo / "api").mkdir(parents=True)
        (repo / "api" / "health.py").write_text("# initial\n", encoding="utf-8")

        compiler = TaskCompiler(repo)
        compiled = compiler.compile({
            "title": req.title,
            "description": req.description,
            "acceptance_criteria": req.acceptance_criteria,
            "target_module": req.target_module,
        })
        assert compiled.requirement.title == req.title
        assert len(compiled.test_specifications) == 1
        assert "GET /health returns 200 OK" in compiled.test_specifications[0].criterion
