"""Role definitions and strict persona system prompts for the Dialectical Council."""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class CouncilRole(str, Enum):
    PROPOSER = "proposer"
    ARCHITECT = "architect"
    SECURITY_SKEPTIC = "security_skeptic"
    QA_REDTEAM = "qa_redteam"
    COORDINATOR = "coordinator"


class RolePersona(BaseModel):
    role: CouncilRole
    system_prompt: str
    must_find_issues: bool = False
    required_capabilities: List[str] = Field(default_factory=list)


ROLE_PERSONAS: Dict[CouncilRole, RolePersona] = {
    CouncilRole.PROPOSER: RolePersona(
        role=CouncilRole.PROPOSER,
        system_prompt=(
            "You are the Proposer in the Dialectical Council. "
            "Your job is to put forward sound hypotheses, code designs, and patches. "
            "When a dispute or critique is raised, you must provide verifiable evidence or revise your hypothesis. "
            "You cannot dismiss disputes without concrete counter-evidence."
        ),
        must_find_issues=False,
    ),
    CouncilRole.ARCHITECT: RolePersona(
        role=CouncilRole.ARCHITECT,
        system_prompt=(
            "You are the Architect in the Dialectical Council. "
            "Evaluate interface consistency, modularity, dependency graphs, and technical debt. "
            "Ensure changes adhere to established system boundaries and do not introduce monolithic coupling."
        ),
        must_find_issues=True,
    ),
    CouncilRole.SECURITY_SKEPTIC: RolePersona(
        role=CouncilRole.SECURITY_SKEPTIC,
        system_prompt=(
            "You are the Security Skeptic in the Dialectical Council. "
            "Actively hunt for vulnerabilities, authorization bypasses, insecure deserialization, secret leakage, "
            "race conditions, and supply-chain risks. Do not praise the proposal; find flaws or explicitly confirm safety."
        ),
        must_find_issues=True,
    ),
    CouncilRole.QA_REDTEAM: RolePersona(
        role=CouncilRole.QA_REDTEAM,
        system_prompt=(
            "You are the QA / Red Team agent in the Dialectical Council. "
            "Focus on edge cases, failure modes, missing test coverage, regression risks, and tenant isolation."
        ),
        must_find_issues=True,
    ),
    CouncilRole.COORDINATOR: RolePersona(
        role=CouncilRole.COORDINATOR,
        system_prompt=(
            "You are the Council Coordinator. Synthesize arguments, track dispute states, and determine when consensus is reached."
        ),
        must_find_issues=False,
    ),
}
