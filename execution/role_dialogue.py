"""Role dialogue: proposal, independent review and revision between two roles.

The foundation principle (completion plan, decision 39) creates intelligence
through dialogue between models from different producers. This module is the
reusable form of that dialogue:

1. the **proposer** role produces a structured proposal from a context packet;
2. a deterministic **fact check** (no language model) verifies the proposal;
3. the **reviewer** role, from a different producer, gets a fixed context
   packet (input, proposal, fact check), never the proposer's conversation,
   and returns findings;
4. the reviewer's findings are fact-checked too: they must point at
   something that exists in the proposal and at known requirements;
5. the proposer revises and answers every finding, at most ``max_revisions``
   times.

Open findings after the last round are recorded as ``disagreement`` for the
human gate; they are never smoothed over. Reviewer approval does not
override a failing fact check. Every answer is schema-validated, and
independence is checked before any model is called.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from jsonschema import ValidationError, validators

from domain.role_process import (
    RoleAssignment,
    RoleCatalog,
    default_catalog,
    validate_assignment,
)
from services.bot_llm_runtime import BoundModel
from services.governed_llm import GovernedLLMRequest

#: Proposer-side field in which every finding must be answered.
RESPONSES_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "finding_id": {"type": "string"},
            "response": {"type": "string"},
            "accepted": {"type": "boolean"},
        },
        "required": ["finding_id", "response", "accepted"],
    },
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "revise"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["blocking", "major", "minor"],
                    },
                    "target": {"type": "string"},
                    "issue": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "severity", "target", "issue", "requirement_ids"],
            },
        },
    },
    "required": ["verdict", "findings"],
}


class RoleDialogueError(RuntimeError):
    """The dialogue cannot produce a trustworthy result."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def requirement_ids_of(kravspec: Mapping[str, Any]) -> list[str]:
    ids = [
        str(item.get("id"))
        for item in kravspec.get("requirements") or []
        if isinstance(item, Mapping)
    ]
    if not ids or any(not i or i == "None" for i in ids):
        raise RoleDialogueError("kravspec has no usable requirement ids")
    return ids


def check_review(
    review: Mapping[str, Any], targets: set[str], requirement_ids: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the reviewer's findings into verified and rejected."""
    known = set(requirement_ids)
    verified, rejected = [], []
    for item in review.get("findings") or []:
        problems = []
        if str(item.get("target")) not in targets:
            problems.append(f"unknown target {item.get('target')!r}")
        unknown = [r for r in item.get("requirement_ids") or [] if r not in known]
        if unknown:
            problems.append(f"unknown requirements {unknown}")
        entry = dict(item)
        if problems:
            entry["rejected_because"] = problems
            rejected.append(entry)
        else:
            verified.append(entry)
    return verified, rejected


@dataclass(frozen=True)
class DialogueSpec:
    """What makes a dialogue an architecture dialogue, a contract dialogue, ..."""

    name: str
    proposer_role: str
    reviewer_role: str
    proposal_schema: Mapping[str, Any]
    proposer_instructions: str
    reviewer_instructions: str
    #: Deterministic fact check of a proposal: returns findings with
    #: ``id``, ``code``, ``target`` and ``issue``.
    fact_check: Callable[[Mapping[str, Any], Mapping[str, Any]], list[dict[str, Any]]]
    #: Everything a reviewer finding may point at in a proposal.
    review_targets: Callable[[Mapping[str, Any]], set[str]]
    #: Context packet keys: what the proposer and the reviewer see.
    input_key: str = "requirements_specification"
    proposal_key: str = "proposal"


@dataclass
class _Turn:
    role: str
    round: int
    model: BoundModel
    session_id: str
    started_at: datetime
    finished_at: datetime | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    replayed: bool = False

    def job(self) -> dict[str, Any]:
        provenance = dict(self.provenance)
        return {
            "role": self.role,
            "round": self.round,
            "session_id": self.session_id,
            "agent": {**self.model.identity.to_dict(), "session_id": self.session_id},
            "prompt_version": self.model.prompt_version,
            "started_at": self.started_at.isoformat(),
            "finished_at": (self.finished_at or self.started_at).isoformat(),
            "usage": {
                "prompt_tokens": provenance.get("prompt_tokens"),
                "completion_tokens": provenance.get("completion_tokens"),
                "total_tokens": provenance.get("total_tokens"),
            },
            "provenance": {
                "prompt_fingerprint": provenance.get("prompt_fingerprint"),
                "output_fingerprint": provenance.get("output_fingerprint"),
                "request_id": provenance.get("request_id"),
                "replayed": self.replayed,
            },
        }


class RoleDialogue:
    def __init__(
        self,
        spec: DialogueSpec,
        proposer: BoundModel,
        reviewer: BoundModel,
        *,
        catalog: RoleCatalog | None = None,
        max_revisions: int = 2,
    ) -> None:
        if max_revisions < 0:
            raise ValueError("max_revisions must be >= 0")
        self._spec = spec
        self._proposer = proposer
        self._reviewer = reviewer
        self._catalog = catalog or default_catalog()
        self._max_revisions = max_revisions
        # Fail before any model is called if the roles are not independent.
        validate_assignment(
            self._catalog,
            RoleAssignment(
                "reviewer",
                spec.name,
                spec.reviewer_role,
                reviewer.identity.brand,
                "reviewer",
            ),
            [
                RoleAssignment(
                    "proposer",
                    spec.name,
                    spec.proposer_role,
                    proposer.identity.brand,
                    "proposer",
                )
            ],
        )

    def run(
        self,
        dialogue_input: Mapping[str, Any],
        *,
        requirement_ids: list[str],
        organization_id: str,
        actor_id: str,
        run_key: str,
    ) -> dict[str, Any]:
        spec = self._spec
        turns: list[_Turn] = []
        rounds: list[dict[str, Any]] = []
        open_findings: list[dict[str, Any]] = []
        proposal: dict[str, Any] | None = None

        for round_number in range(1, self._max_revisions + 2):
            proposal = self._call(
                turns,
                spec.proposer_role,
                round_number,
                self._proposer,
                spec.proposer_instructions,
                spec.proposal_schema,
                {
                    **dict(dialogue_input),
                    f"previous_{spec.proposal_key}": proposal,
                    "review_findings": open_findings,
                },
                organization_id,
                actor_id,
                run_key,
            )
            fact_check = spec.fact_check(proposal, dialogue_input)
            review = self._call(
                turns,
                spec.reviewer_role,
                round_number,
                self._reviewer,
                spec.reviewer_instructions,
                REVIEW_SCHEMA,
                {
                    **dict(dialogue_input),
                    spec.proposal_key: proposal,
                    "fact_check_findings": fact_check,
                },
                organization_id,
                actor_id,
                run_key,
            )
            verified, rejected = check_review(
                review, spec.review_targets(proposal), requirement_ids
            )
            blocking = [f for f in verified if f["severity"] in {"blocking", "major"}]
            rounds.append(
                {
                    "round": round_number,
                    "proposal_fingerprint": fingerprint(proposal),
                    "fact_check": fact_check,
                    "verdict": review.get("verdict"),
                    "findings": verified,
                    "rejected_findings": rejected,
                    "responses_to_findings": list(
                        proposal.get("responses_to_findings") or []
                    ),
                }
            )
            open_findings = [
                *(
                    {
                        "id": f["id"],
                        "code": f.get("code"),
                        "severity": "blocking",
                        "target": f["target"],
                        "issue": f["issue"],
                        "requirement_ids": [],
                        "source": "fact_check",
                    }
                    for f in fact_check
                ),
                *({**f, "source": "reviewer"} for f in blocking),
            ]
            if not open_findings and review.get("verdict") == "approve":
                break

        assert proposal is not None
        return {
            "status": "agreed" if not open_findings else "disagreement",
            "proposal": proposal,
            "proposal_fingerprint": fingerprint(proposal),
            "rounds": rounds,
            "open_findings": open_findings,
            "requirement_ids": list(requirement_ids),
            "roles": {
                spec.proposer_role: self._proposer.identity.to_dict(),
                spec.reviewer_role: self._reviewer.identity.to_dict(),
            },
            "agent_jobs": [turn.job() for turn in turns],
        }

    def _call(
        self,
        turns: list[_Turn],
        role: str,
        round_number: int,
        model: BoundModel,
        instructions: str,
        schema: Mapping[str, Any],
        context_packet: Mapping[str, Any],
        organization_id: str,
        actor_id: str,
        run_key: str,
    ) -> dict[str, Any]:
        session_id = f"{run_key}:{role}:r{round_number}"
        turn = _Turn(
            role=role,
            round=round_number,
            model=model,
            session_id=session_id,
            started_at=_now(),
        )
        result = model.runtime.generate(
            GovernedLLMRequest(
                organization_id=organization_id,
                actor_id=actor_id,
                idempotency_key=session_id,
                purpose=f"{self._spec.name}:{role}",
                model=model.model,
                instructions=instructions,
                untrusted_input=context_packet,
                output_schema=schema,
                max_input_tokens=model.max_input_tokens,
                max_output_tokens=model.max_output_tokens,
            )
        )
        turn.finished_at = _now()
        turn.provenance = dict(result.provenance.__dict__)
        turn.replayed = result.replayed
        turns.append(turn)
        value = dict(result.value)
        try:
            validators.validator_for(schema)(schema).validate(value)
        except ValidationError as exc:
            raise RoleDialogueError(
                f"{role} answer in round {round_number} does not match its schema: {exc.message}"
            ) from exc
        return value
