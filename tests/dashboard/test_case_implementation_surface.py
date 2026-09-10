"""Surface contract for Execution start + Implementation Proposal in Sag."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SURFACE = ROOT / "dashboard" / "case_implementation.py"
CLARIFICATION = ROOT / "dashboard" / "case_clarification.py"
MAIN = ROOT / "api" / "main.py"
ENDPOINT = ROOT / "api" / "endpoints" / "case_execution.py"


def test_execution_start_uses_project_scoped_backend_boundary() -> None:
    source = SURFACE.read_text(encoding="utf-8")

    assert "/api/v1/control-plane/projects/{project_id}/execution" in source
    assert "plan_request_fingerprint" in source
    assert '"Start arbejdet"' in source
    assert "/api/v1/execution/start" not in source


def test_implementation_proposal_is_bounded_and_does_not_apply_patch() -> None:
    source = SURFACE.read_text(encoding="utf-8")

    assert '"Generér Implementation Proposal"' in source
    assert "ImplementationScope" in source
    assert "allowed_paths" in source
    assert "max_changed_lines" in source
    assert 'client.post("/implementation-agent/proposals"' in source
    assert 'client.post("/implementation-agent/executions"' not in source
    assert "Patch Apply er en separat capability" in source


def test_case_flow_reaches_execution_without_legacy_page_navigation() -> None:
    clarification = CLARIFICATION.read_text(encoding="utf-8")
    surface = SURFACE.read_text(encoding="utf-8")

    assert "render_case_execution_implementation(client, item)" in clarification
    assert "st.page_link" not in surface
    assert "operator_nav" not in surface


def test_project_scoped_execution_router_is_canonical_and_fail_closed() -> None:
    main = MAIN.read_text(encoding="utf-8")
    endpoint = ENDPOINT.read_text(encoding="utf-8")

    assert "case_execution.router" in main
    assert "case_execution.__name__" in main
    assert "_require_active_scope(project, request.plan_request_fingerprint)" in endpoint
    assert 'detail={"error": "stale_project_scope"}' in endpoint
    assert "project_id=project_id" in endpoint
    assert "plan_request_fingerprint=request.plan_request_fingerprint" in endpoint
