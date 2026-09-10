"""Fail-closed presentation provenance for case-bound implementation proposals.

The helper only links identifiers when the proposal result and the backend
execution snapshot agree on the exact Case and active-plan fingerprint. It does
not create provenance, infer ownership, or grant authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PROPOSAL_RESULTS_KEY = "case_implementation_proposals"


@dataclass(frozen=True)
class ProposalProvenance:
    case_id: str
    plan_id: str
    execution_id: str
    proposal_id: str
    proposal_execution_id: str | None = None


def _text(value: Any) -> str:
    return str(value or "").strip()


def proposal_results_for_case(
    cached_results: Any,
    case_id: str,
) -> tuple[dict[str, Any], ...]:
    """Return cached proposal results that explicitly name the selected Case."""
    if not isinstance(cached_results, Mapping):
        return ()
    selected = _text(case_id)
    return tuple(
        dict(value)
        for value in cached_results.values()
        if isinstance(value, Mapping) and _text(value.get("project_id")) == selected
    )


def resolve_proposal_provenance(
    *,
    case_id: str,
    execution: Mapping[str, Any] | None,
    proposal_result: Mapping[str, Any],
) -> ProposalProvenance | None:
    """Resolve Case → Plan → Execution → Proposal only from matching backend facts."""
    selected_case_id = _text(case_id)
    result_case_id = _text(proposal_result.get("project_id"))
    plan_id = _text(proposal_result.get("plan_id"))
    plan_fingerprint = _text(proposal_result.get("plan_request_fingerprint"))
    if not selected_case_id or result_case_id != selected_case_id:
        return None
    if not plan_id or not plan_fingerprint or not isinstance(execution, Mapping):
        return None

    execution_case_id = _text(execution.get("project_id"))
    execution_plan_fingerprint = _text(execution.get("plan_request_fingerprint"))
    execution_id = _text(execution.get("workflow_id"))
    if (
        execution_case_id != selected_case_id
        or execution_plan_fingerprint != plan_fingerprint
        or not execution_id
    ):
        return None

    response = proposal_result.get("response")
    if not isinstance(response, Mapping):
        return None
    proposal = response.get("proposal")
    if not isinstance(proposal, Mapping):
        return None
    proposal_id = _text(proposal.get("proposal_id"))
    if not proposal_id:
        return None

    proposal_execution_id = _text(response.get("execution_id")) or None
    return ProposalProvenance(
        case_id=selected_case_id,
        plan_id=plan_id,
        execution_id=execution_id,
        proposal_id=proposal_id,
        proposal_execution_id=proposal_execution_id,
    )
