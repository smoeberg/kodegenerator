"""Prompt producer and prompt reviewer in dialogue (decision 42).

The prompt producer writes a new version of the prompt for one agent role
and purpose; the prompt reviewer, from a different producer, challenges it;
a deterministic fact check guards what must never be lost. An agreed
proposal is written to ``config/prompts/<role>/<purpose>.v<N>.md`` with
status ``proposed``. It runs only after the project board approves it by
merging the change that makes it ``trial`` or ``active``; nothing here can
activate a prompt.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from domain.prompt_registry import PROMPTS_PATH, PromptRegistry, prompt
from domain.role_process import RoleCatalog, default_catalog
from execution.role_dialogue import RESPONSES_SCHEMA, DialogueSpec, RoleDialogue
from services.bot_llm_runtime import BoundModel

PRODUCER_ROLE = "prompt_producer"
REVIEWER_ROLE = "prompt_reviewer"
MAX_PROMPT_CHARS = 6_000

PRODUCER_PROMPT = prompt(PRODUCER_ROLE, "write_prompt")
REVIEWER_PROMPT = prompt(REVIEWER_ROLE, "review_prompt")

PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "change_summary": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "responses_to_findings": RESPONSES_SCHEMA,
    },
    "required": ["text", "change_summary", "assumptions"],
}

#: Text a prompt must never contain: it would hand a role authority or
#: context that the role process forbids.
_FORBIDDEN = [
    (
        re.compile(r"\byou (?:may|can|should) approve\b", re.IGNORECASE),
        "lets the role approve",
    ),
    (
        re.compile(
            r"\bskip (?:the )?(?:fact check|control|review|tests?)\b", re.IGNORECASE
        ),
        "skips a control",
    ),
    (
        re.compile(
            r"\btrust (?:the )?(?:coder|agent|author)'?s? (?:report|claims?)\b",
            re.IGNORECASE,
        ),
        "trusts another agent's report",
    ),
    (
        re.compile(r"\b(?:sk|api)[-_][A-Za-z0-9]{16,}\b"),
        "contains something that looks like a key",
    ),
]


def check_prompt(
    proposal: Mapping[str, Any], dialogue_input: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Deterministic fact check of a proposed prompt. No language model."""
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

    text = str(proposal.get("text") or "")
    role = dialogue_input["role"]
    current = str(dialogue_input["current_prompt"]["text"])
    if not text.strip():
        finding("empty", "text", "the prompt is empty")
        return findings
    if len(text) > MAX_PROMPT_CHARS:
        finding(
            "too_long",
            "text",
            f"the prompt has {len(text)} characters, the limit is {MAX_PROMPT_CHARS}",
        )
    names = {role["id"], role["name"].lower(), role["id"].replace("_", " ")}
    if not any(n.lower() in text.lower() for n in names):
        finding(
            "role_not_named", "text", f"the prompt does not name its role {role['id']}"
        )
    if "untrusted" not in text.lower():
        finding(
            "untrusted_input",
            "text",
            "the prompt must say that project data is untrusted input",
        )
    for pattern, issue in _FORBIDDEN:
        if pattern.search(text):
            finding("forbidden", "text", f"the prompt {issue}")
    # Safety rules of the current version are kept: every sentence of the
    # current prompt that names a control or independence must survive in spirit;
    # the deterministic part checks the key words did not disappear.
    for word in ("independent", "different producer", "never see", "not evidence"):
        if word in current.lower() and word not in text.lower():
            finding(
                "safety_rule_dropped",
                "text",
                f"the current prompt says {word!r}; the proposal does not",
            )
    # Placeholders the factory fills in ({allowed_paths}) must survive; new ones
    # would reach the agent unfilled.
    placeholder = re.compile(r"\{[a-z_]+\}")
    before, after = set(placeholder.findall(current)), set(placeholder.findall(text))
    for name in sorted(before - after):
        finding(
            "placeholder_dropped", "text", f"the proposal drops the placeholder {name}"
        )
    for name in sorted(after - before):
        finding("unknown_placeholder", "text", f"the factory does not fill {name}")
    if not str(proposal.get("change_summary") or "").strip():
        finding(
            "no_change_summary",
            "change_summary",
            "a new version needs a change summary",
        )
    if text.strip() == current.strip():
        finding("unchanged", "text", "the proposal is identical to the active version")
    return findings


PROMPT_DIALOGUE = DialogueSpec(
    name="prompt-council",
    proposer_role=PRODUCER_ROLE,
    reviewer_role=REVIEWER_ROLE,
    proposal_schema=PROPOSAL_SCHEMA,
    proposer_instructions=PRODUCER_PROMPT.text,
    reviewer_instructions=REVIEWER_PROMPT.text,
    proposer_prompt_version=PRODUCER_PROMPT.ref,
    reviewer_prompt_version=REVIEWER_PROMPT.ref,
    fact_check=check_prompt,
    review_targets=lambda _proposal: {"text", "change_summary", "general"},
    input_key="role",
)


class PromptCouncil:
    def __init__(
        self,
        producer: BoundModel,
        reviewer: BoundModel,
        *,
        catalog: RoleCatalog | None = None,
        root: Path = PROMPTS_PATH,
        max_revisions: int = 2,
    ) -> None:
        self._catalog = catalog or default_catalog()
        self._root = root
        self._dialogue = RoleDialogue(
            PROMPT_DIALOGUE,
            producer,
            reviewer,
            catalog=self._catalog,
            max_revisions=max_revisions,
        )

    def propose(
        self,
        role_id: str,
        purpose: str,
        change_request: str,
        *,
        organization_id: str,
        actor_id: str,
        house_rules: list[Mapping[str, Any]] | None = None,
        statistics: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the dialogue; write an agreed proposal as a ``proposed`` version."""
        if not change_request.strip():
            raise ValueError("a prompt change needs a change request")
        registry = PromptRegistry.load(self._root, self._catalog)
        current = registry.active(role_id, purpose)
        spec = self._catalog.role(role_id)
        version = registry.next_version(role_id, purpose)
        outcome = self._dialogue.run(
            {
                "role": {
                    "id": spec.id,
                    "name": spec.name,
                    "layer": spec.layer.value,
                    "authority": spec.authority.value,
                    "owns": spec.owns,
                    "input": spec.input,
                    "output": spec.output,
                    "controlled_by": list(spec.controlled_by),
                },
                "purpose": purpose,
                "current_prompt": {"ref": current.ref, "text": current.text},
                "change_request": change_request,
                "house_rules": list(house_rules or []),
                "statistics": dict(statistics or {}),
            },
            requirement_ids=[purpose],
            organization_id=organization_id,
            actor_id=actor_id,
            run_key=f"prompt:{role_id}:{purpose}:v{version}",
        )
        outcome["role"], outcome["purpose"], outcome["version"] = (
            role_id,
            purpose,
            version,
        )
        outcome["replaces"] = current.ref
        if outcome["status"] == "agreed":
            outcome["path"] = str(self._write(role_id, purpose, version, outcome))
        return outcome

    def _write(
        self, role_id: str, purpose: str, version: int, outcome: Mapping[str, Any]
    ) -> Path:
        proposal = outcome["proposal"]
        header = {
            "role": role_id,
            "purpose": purpose,
            "version": version,
            "status": "proposed",
            "author": "prompt council: "
            + ", ".join(
                f"{j['role']}={j['agent'].get('brand')}"
                for j in outcome["agent_jobs"][-2:]
            ),
            "replaces": outcome["replaces"],
            "change_summary": proposal["change_summary"],
            "assumptions": list(proposal.get("assumptions") or []),
        }
        path = self._root / role_id / f"{purpose}.v{version}.md"
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            + yaml.safe_dump(header, sort_keys=False, allow_unicode=True)
            + "---\n"
            + proposal["text"].strip()
            + "\n",
            encoding="utf-8",
        )
        return path


def default_prompt_council(organization_id: str) -> PromptCouncil | None:
    """``DOR_PROMPT_PRODUCER_BOT_PROFILE`` and ``DOR_PROMPT_REVIEWER_BOT_PROFILE``:
    both or neither (fail closed on one)."""
    import os

    producer = os.getenv("DOR_PROMPT_PRODUCER_BOT_PROFILE", "").strip()
    reviewer = os.getenv("DOR_PROMPT_REVIEWER_BOT_PROFILE", "").strip()
    if not producer and not reviewer:
        return None
    if not producer or not reviewer:
        raise RuntimeError(
            "DOR_PROMPT_PRODUCER_BOT_PROFILE and DOR_PROMPT_REVIEWER_BOT_PROFILE must both be set"
        )
    from api.dependencies import resolve_bot_model_for

    return PromptCouncil(
        resolve_bot_model_for(organization_id, producer),
        resolve_bot_model_for(organization_id, reviewer),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    parser = argparse.ArgumentParser(
        description="Propose a new prompt version (decision 42)."
    )
    parser.add_argument("--organization", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument("--request", required=True, help="the change request")
    args = parser.parse_args(argv)
    council = default_prompt_council(args.organization)
    if council is None:
        print("no prompt council configured", file=sys.stderr)
        return 2
    outcome = council.propose(
        args.role,
        args.purpose,
        args.request,
        organization_id=args.organization,
        actor_id=args.actor,
    )
    print(
        json.dumps(
            {
                k: outcome.get(k)
                for k in ("status", "path", "version", "replaces", "open_findings")
            },
            indent=2,
        )
    )
    return 0 if outcome["status"] == "agreed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
