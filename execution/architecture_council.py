"""Architecture council: completion plan step 3.

A dialogue between two roles from the role-process catalog (decision 39):

* the **architect** proposes an architecture from the approved kravspec;
* the **architecture reviewer**, from a different producer, challenges it;
* the architect revises, at most ``max_revisions`` times.

Between the turns a deterministic fact check (no language model) verifies
the proposal against the kravspec and verifies the reviewer's findings
against the proposal. Disagreement is a signal: what is still open after
the last round is recorded and goes to the project manager at the
architecture gate; it is never smoothed over. Agreement is not proof: the
fact check runs on every proposal regardless of what the reviewer says.

The reviewer gets a fixed context packet (kravspec, proposal, fact-check
result), never the architect's conversation.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.prompt_registry import prompt
from domain.role_process import RoleCatalog
from execution.role_dialogue import (
    RESPONSES_SCHEMA,
    DialogueSpec,
    RoleDialogue,
    RoleDialogueError,
    requirement_ids_of,
)
from execution.role_dialogue import check_review as _check_review
from services.bot_llm_runtime import BoundModel

ARCHITECT_ROLE = "architect"
REVIEWER_ROLE = "architecture_reviewer"

PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stack": {
            "type": "object",
            "properties": {
                "language": {"type": "string"},
                "framework": {"type": "string"},
                "persistence": {"type": "string"},
                "rationale": {"type": "string"},
            },
            "required": ["language", "framework", "persistence", "rationale"],
        },
        "modules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "responsibility": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "interfaces": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "kind": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["name", "kind", "description"],
                        },
                    },
                },
                "required": [
                    "id",
                    "responsibility",
                    "requirement_ids",
                    "depends_on",
                    "interfaces",
                ],
            },
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "decision": {"type": "string"},
                    "rationale": {"type": "string"},
                    "requirement_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "decision", "rationale", "requirement_ids"],
            },
        },
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "responses_to_findings": RESPONSES_SCHEMA,
    },
    "required": ["stack", "modules", "decisions", "assumptions"],
}

ARCHITECT_PROMPT = prompt("architect", "propose_architecture")
ARCHITECT_INSTRUCTIONS = ARCHITECT_PROMPT.text

REVIEWER_PROMPT = prompt("architecture_reviewer", "review_architecture")
REVIEWER_INSTRUCTIONS = REVIEWER_PROMPT.text


#: Kept as the architecture-specific name for dialogue failures.
ArchitectureCouncilError = RoleDialogueError


# --------------------------------------------------------------------- #
# Deterministic fact check (no language model)
# --------------------------------------------------------------------- #
def check_proposal(
    proposal: Mapping[str, Any], requirement_ids: list[str]
) -> list[dict[str, Any]]:
    """Verify the proposal's references and structure against the kravspec."""
    known = set(requirement_ids)
    findings: list[dict[str, Any]] = []

    def finding(code: str, target: str, issue: str) -> None:
        findings.append(
            {
                "id": f"FC-{len(findings) + 1}",
                "code": code,
                "target": target,
                "issue": issue,
            }
        )

    modules = list(proposal.get("modules") or [])
    module_ids = [str(m.get("id")) for m in modules]
    if not modules:
        finding("no_modules", "modules", "the proposal has no modules")
    for duplicate in sorted({m for m in module_ids if module_ids.count(m) > 1}):
        finding("duplicate_module", duplicate, "module id is used more than once")
    covered: set[str] = set()
    for module in modules:
        mid = str(module.get("id"))
        refs = [str(r) for r in module.get("requirement_ids") or []]
        if not refs:
            finding(
                "module_without_requirement", mid, "module refers to no requirement"
            )
        for ref in refs:
            if ref not in known:
                finding(
                    "unknown_requirement", mid, f"refers to unknown requirement {ref}"
                )
        covered.update(r for r in refs if r in known)
        for dep in module.get("depends_on") or []:
            if dep not in module_ids:
                finding("unknown_dependency", mid, f"depends on unknown module {dep}")
            if dep == mid:
                finding("self_dependency", mid, "module depends on itself")
    for missing in [r for r in requirement_ids if r not in covered]:
        finding("uncovered_requirement", missing, "requirement is covered by no module")
    for decision in proposal.get("decisions") or []:
        for ref in decision.get("requirement_ids") or []:
            if ref not in known:
                finding(
                    "unknown_requirement",
                    str(decision.get("id")),
                    f"refers to unknown requirement {ref}",
                )
    if cycle := _dependency_cycle(modules):
        finding(
            "dependency_cycle", " -> ".join(cycle), "module dependencies form a cycle"
        )
    return findings


def _dependency_cycle(modules: list[Mapping[str, Any]]) -> list[str] | None:
    graph = {
        str(m.get("id")): [str(d) for d in m.get("depends_on") or []] for m in modules
    }
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> list[str] | None:
        state[node] = 1
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                return path + [node, nxt]
            if state.get(nxt) is None and (found := visit(nxt, path + [node])):
                return found
        state[node] = 2
        return None

    for node in graph:
        if state.get(node) is None and (found := visit(node, [])):
            return found
    return None


def independent_modules(proposal: Mapping[str, Any]) -> list[list[str]]:
    """Modules grouped in build layers; modules in one layer can be built in parallel."""
    graph = {
        str(m["id"]): {str(d) for d in m.get("depends_on") or []}
        for m in proposal.get("modules") or []
    }
    layers: list[list[str]] = []
    done: set[str] = set()
    while len(done) < len(graph):
        layer = sorted(m for m, deps in graph.items() if m not in done and deps <= done)
        if not layer:
            break
        layers.append(layer)
        done.update(layer)
    return layers


def review_targets(proposal: Mapping[str, Any]) -> set[str]:
    return (
        {"stack"}
        | {str(m.get("id")) for m in proposal.get("modules") or []}
        | {str(d.get("id")) for d in proposal.get("decisions") or []}
    )


def check_review(
    review: Mapping[str, Any], proposal: Mapping[str, Any], requirement_ids: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reviewers are checked too (plan, fact check rule 5)."""
    return _check_review(review, review_targets(proposal), requirement_ids)


ARCHITECTURE_DIALOGUE = DialogueSpec(
    name="architecture-council",
    proposer_role=ARCHITECT_ROLE,
    reviewer_role=REVIEWER_ROLE,
    proposal_schema=PROPOSAL_SCHEMA,
    proposer_instructions=ARCHITECT_INSTRUCTIONS,
    reviewer_instructions=REVIEWER_INSTRUCTIONS,
    proposer_prompt_version=ARCHITECT_PROMPT.ref,
    reviewer_prompt_version=REVIEWER_PROMPT.ref,
    fact_check=lambda proposal, dialogue_input: check_proposal(
        proposal, requirement_ids_of(dialogue_input["requirements_specification"])
    ),
    review_targets=review_targets,
)


class ArchitectureCouncil:
    """The architect and the architecture reviewer in dialogue (step 3)."""

    def __init__(
        self,
        architect: BoundModel,
        reviewer: BoundModel,
        *,
        catalog: RoleCatalog | None = None,
        max_revisions: int = 2,
    ) -> None:
        self._dialogue = RoleDialogue(
            ARCHITECTURE_DIALOGUE,
            architect,
            reviewer,
            catalog=catalog,
            max_revisions=max_revisions,
        )

    def run(
        self,
        kravspec: Mapping[str, Any],
        *,
        organization_id: str,
        actor_id: str,
        run_key: str,
    ) -> dict[str, Any]:
        requirement_ids = requirement_ids_of(kravspec)
        outcome = self._dialogue.run(
            {"requirements_specification": dict(kravspec)},
            requirement_ids=requirement_ids,
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=run_key,
        )
        proposal = outcome["proposal"]
        outcome["build_layers"] = (
            independent_modules(proposal)
            if not check_proposal(proposal, requirement_ids)
            else []
        )
        return outcome
