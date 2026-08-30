"""Deterministic requirement normalization shared by pipeline generators."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class GherkinScenario:
    title: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class IngestedRequirement:
    id: str
    title: str
    description: str
    target_module: str
    acceptance_criteria: tuple[str, ...]
    priority: str = "must"


@dataclass(frozen=True)
class IngestedSpecification:
    project_name: str
    requirements: tuple[IngestedRequirement, ...]
    fingerprint: str


def parse_gherkin_scenarios(text: str) -> tuple[GherkinScenario, ...]:
    """Parse Gherkin feature text into structured scenarios."""
    scenarios: list[GherkinScenario] = []
    current_title: str | None = None
    current_steps: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        scenario_match = re.match(r"^Scenario:\s*(.*)$", stripped, re.IGNORECASE)
        if scenario_match:
            if current_title:
                scenarios.append(GherkinScenario(current_title, tuple(current_steps)))
            current_title = scenario_match.group(1).strip()
            current_steps = []
            continue

        step_match = re.match(r"^(Given|When|Then|And|But)\s+(.*)$", stripped, re.IGNORECASE)
        if step_match and current_title:
            current_steps.append(f"{step_match.group(1)} {step_match.group(2).strip()}")

    if current_title:
        scenarios.append(GherkinScenario(current_title, tuple(current_steps)))

    return tuple(scenarios)


def ingest_unstructured_requirements(
    document: str, *, project_name: str
) -> IngestedSpecification:
    """Extract structured requirements, target modules and criteria from unstructured docs/markdown."""
    lines = document.splitlines()
    requirements: list[IngestedRequirement] = []
    
    current_id: str | None = None
    current_title: str | None = None
    current_desc_lines: list[str] = []
    current_target: str = "src/main.py"
    current_criteria: list[str] = []
    current_priority: str = "must"

    def flush_current():
        nonlocal current_id, current_title, current_desc_lines, current_target, current_criteria, current_priority
        if current_id or current_title:
            req_id = current_id or f"REQ-{len(requirements)+1:03d}"
            title = current_title or req_id
            description = " ".join(" ".join(current_desc_lines).split()) or title
            if not current_criteria:
                current_criteria.append(f"Satisfies {title}")
            requirements.append(
                IngestedRequirement(
                    id=req_id,
                    title=title,
                    description=description,
                    target_module=current_target,
                    acceptance_criteria=tuple(current_criteria),
                    priority=current_priority,
                )
            )
        current_id = None
        current_title = None
        current_desc_lines = []
        current_target = "src/main.py"
        current_criteria = []
        current_priority = "must"

    header_re = re.compile(r"^#+\s*(?:(REQ-[0-9]+|FR-[0-9]+)[:\s-]*)?(.*)$", re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for section header
        if stripped.startswith("#"):
            match = header_re.match(stripped)
            if match:
                raw_id, raw_title = match.groups()
                # If header has REQ- or looks like a requirement
                if raw_id:
                    flush_current()
                    current_id = raw_id.upper()
                    current_title = raw_title.strip() if raw_title else raw_id.upper()
                    continue
                elif "requirement:" in stripped.lower() or "requirement -" in stripped.lower():
                    flush_current()
                    current_id = None
                    current_title = raw_title.strip() if raw_title else "Requirement"
                    continue
                else:
                    # Non-requirement section like "# Requirements" or "## Overview"
                    continue

        target_match = re.match(r"^Target(?:\s*Module)?:\s*([^\s]+)$", stripped, re.IGNORECASE)
        if target_match:
            current_target = target_match.group(1).strip()
            continue

        priority_match = re.match(r"^(Must|Should|Could|Wont)\b", stripped, re.IGNORECASE)
        if priority_match and not stripped.startswith("-"):
            current_priority = priority_match.group(1).lower()

        if stripped.startswith(("-", "*", "•")):
            criterion = stripped.lstrip("-*• ").strip()
            if criterion:
                current_criteria.append(criterion)
            continue

        current_desc_lines.append(stripped)

    flush_current()

    if not requirements:
        raise ValueError("no requirements could be extracted from the document")

    canonical = json.dumps(
        [
            {
                "id": r.id,
                "title": r.title,
                "target_module": r.target_module,
                "criteria": r.acceptance_criteria,
            }
            for r in requirements
        ],
        sort_keys=True,
    )
    return IngestedSpecification(
        project_name=project_name,
        requirements=tuple(requirements),
        fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


@dataclass(frozen=True)
class RequirementCriterion:
    criterion_id: str
    statement: str
    requirement_id: str


@dataclass(frozen=True)
class RequirementAnalysis:
    project_name: str
    criteria: tuple[RequirementCriterion, ...]
    fingerprint: str


def analyze_requirements(source: Any, *, project_name: str) -> RequirementAnalysis:
    """Normalize YAML/dict requirements into stable, traceable criteria."""
    if isinstance(source, str):
        try:
            payload = yaml.safe_load(source) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid requirements YAML: {exc}") from exc
    elif isinstance(source, dict):
        payload = source
    else:
        payload = {}
    raw_requirements = payload.get("requirements", [])
    if not isinstance(raw_requirements, list) or not raw_requirements:
        raise ValueError(
            "pipeline requirements must contain a non-empty requirements list"
        )
    criteria: list[RequirementCriterion] = []
    for req_index, requirement in enumerate(raw_requirements, start=1):
        if not isinstance(requirement, dict):
            raise ValueError("each requirement must be an object")
        requirement_id = str(requirement.get("id") or f"REQ-{req_index:03d}")
        raw_criteria = requirement.get("acceptance_criteria") or []
        if not isinstance(raw_criteria, list) or not raw_criteria:
            raise ValueError(f"requirement {requirement_id} has no acceptance criteria")
        for criterion_index, statement in enumerate(raw_criteria, start=1):
            normalized = " ".join(str(statement).split())
            if not normalized:
                raise ValueError("acceptance criteria must be non-empty")
            digest = hashlib.sha256(normalized.encode()).hexdigest()[:10]
            criteria.append(
                RequirementCriterion(
                    f"{requirement_id}-AC-{criterion_index:03d}-{digest}",
                    normalized,
                    requirement_id,
                )
            )
    canonical = json.dumps(
        [(item.criterion_id, item.statement) for item in criteria],
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return RequirementAnalysis(
        project_name=project_name,
        criteria=tuple(criteria),
        fingerprint=hashlib.sha256(canonical.encode()).hexdigest(),
    )


def http_expectation(statement: str) -> tuple[str, str, int] | None:
    """Extract an explicit HTTP method/path/status assertion when present."""
    match = re.search(
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+([^\s]+).*?"
        r"\b(?:returns?|responds? with)\s+(\d{3})\b",
        statement,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).upper(), match.group(2), int(match.group(3))
