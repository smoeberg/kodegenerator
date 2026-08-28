"""Deterministic requirement normalization shared by pipeline generators."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import yaml


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
