"""Task producer and system architect in dialogue (decision 41).

The task producer (an agent) proposes how the approved module contracts are
split into work packages. The task compiler is its fact check; the system
architect, from a different producer, challenges the split against the
architecture. An agreed split is compiled into the work plan the project
board approves at the contracts gate. Without an agreed split there is no
work plan from this path: the board sees the disagreement.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

from domain.prompt_registry import prompt
from domain.role_process import RoleCatalog
from execution.role_dialogue import RESPONSES_SCHEMA, DialogueSpec, RoleDialogue
from execution.task_compiler import check_split
from services.bot_llm_runtime import BoundModel

PRODUCER_ROLE = "task_producer"
REVIEWER_ROLE = "system_architect"
PRODUCER_PROMPT = prompt(PRODUCER_ROLE, "split_tasks")
REVIEWER_PROMPT = prompt(REVIEWER_ROLE, "review_task_split")

SPLIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "packages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "package_id": {"type": "string"},
                    "module_id": {"type": "string"},
                    "description": {"type": "string"},
                    "weight": {"type": "integer"},
                    "owned_paths": {"type": "array", "items": {"type": "string"}},
                    "criterion_ids": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "package_id",
                    "module_id",
                    "description",
                    "weight",
                    "owned_paths",
                    "criterion_ids",
                    "depends_on",
                ],
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "responses_to_findings": RESPONSES_SCHEMA,
    },
    "required": ["packages", "assumptions"],
}


def _targets(split: Mapping[str, Any]) -> set[str]:
    return (
        {str(p.get("package_id")) for p in split.get("packages") or []}
        | {str(p.get("module_id")) for p in split.get("packages") or []}
        | {"general"}
    )


TASK_DIALOGUE = DialogueSpec(
    name="task-council",
    proposer_role=PRODUCER_ROLE,
    reviewer_role=REVIEWER_ROLE,
    proposal_schema=SPLIT_SCHEMA,
    proposer_instructions=PRODUCER_PROMPT.text,
    reviewer_instructions=REVIEWER_PROMPT.text,
    proposer_prompt_version=PRODUCER_PROMPT.ref,
    reviewer_prompt_version=REVIEWER_PROMPT.ref,
    fact_check=lambda split, dialogue_input: check_split(
        split,
        dialogue_input["contracts"]["modules"],
        dialogue_input["contracts"]["acceptance_criteria"],
    ),
    review_targets=_targets,
)


class TaskCouncil:
    def __init__(
        self,
        producer: BoundModel,
        architect: BoundModel,
        *,
        catalog: RoleCatalog | None = None,
        max_revisions: int = 2,
    ) -> None:
        self._dialogue = RoleDialogue(
            TASK_DIALOGUE,
            producer,
            architect,
            catalog=catalog,
            max_revisions=max_revisions,
        )

    def run(
        self,
        contracts: Mapping[str, Any],
        architecture: Mapping[str, Any],
        kravspec: Mapping[str, Any],
        *,
        organization_id: str,
        actor_id: str,
        run_key: str,
    ) -> dict[str, Any]:
        requirement_ids = sorted(
            {str(r.get("id")) for r in kravspec.get("requirements") or []}
        )
        return self._dialogue.run(
            {
                "contracts": {
                    "modules": list(contracts.get("modules") or []),
                    "acceptance_criteria": list(
                        contracts.get("acceptance_criteria") or []
                    ),
                },
                "approved_architecture": dict(architecture),
                "requirements": list(kravspec.get("requirements") or []),
            },
            requirement_ids=requirement_ids,
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=f"{run_key}:tasks",
        )


class TaskCouncilConfigurationError(RuntimeError):
    pass


def default_task_council(organization_id: str) -> TaskCouncil | None:
    """``DOR_TASK_PRODUCER_BOT_PROFILE`` and ``DOR_SYSTEM_ARCHITECT_BOT_PROFILE``:
    both or neither; only one fails closed."""
    producer = os.getenv("DOR_TASK_PRODUCER_BOT_PROFILE", "").strip()
    architect = os.getenv("DOR_SYSTEM_ARCHITECT_BOT_PROFILE", "").strip()
    if not producer and not architect:
        return None
    if not producer or not architect:
        raise TaskCouncilConfigurationError(
            "DOR_TASK_PRODUCER_BOT_PROFILE and DOR_SYSTEM_ARCHITECT_BOT_PROFILE must both be set"
        )
    from api.dependencies import resolve_bot_model_for

    return TaskCouncil(
        resolve_bot_model_for(organization_id, producer),
        resolve_bot_model_for(organization_id, architect),
    )
