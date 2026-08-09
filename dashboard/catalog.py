"""Descriptive dashboard catalog with no runtime authority semantics."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class CapabilityLevel(str, Enum):
    ADVANCED = "advanced"
    EXPERT = "expert"


@dataclass(frozen=True)
class DashboardCapability:
    id: str
    name: str
    description: str
    level: CapabilityLevel


@dataclass(frozen=True)
class DashboardRoleTemplate:
    """Presentation-only role template; it never grants runtime authority."""

    id: str
    name: str
    description: str
    capabilities: tuple[str, ...]
    authority: Mapping[str, bool]
    responsibilities: tuple[str, ...]


STANDARD_CAPABILITIES: Mapping[str, DashboardCapability] = MappingProxyType(
    {
        "code_generation": DashboardCapability(
            id="cap_code_gen",
            name="Code Generation",
            description="Generate implementation code from approved requirements.",
            level=CapabilityLevel.EXPERT,
        ),
        "code_review": DashboardCapability(
            id="cap_code_review",
            name="Code Review & Quality Gate",
            description="Review code quality, security, and conformance.",
            level=CapabilityLevel.EXPERT,
        ),
        "architecture_design": DashboardCapability(
            id="cap_arch_design",
            name="System Architecture & ADR",
            description="Design systems and record architecture decisions.",
            level=CapabilityLevel.ADVANCED,
        ),
        "test_automation": DashboardCapability(
            id="cap_test_auto",
            name="Automated Testing",
            description="Create deterministic automated tests.",
            level=CapabilityLevel.ADVANCED,
        ),
        "governance_approval": DashboardCapability(
            id="cap_gov_approve",
            name="Governance Gate Sign-off",
            description="Review and sign governed artifacts.",
            level=CapabilityLevel.EXPERT,
        ),
    }
)


def _authority(**values: bool) -> Mapping[str, bool]:
    return MappingProxyType(values)


STANDARD_ROLES: Mapping[str, DashboardRoleTemplate] = MappingProxyType(
    {
        "role_senior_developer": DashboardRoleTemplate(
            id="role_senior_developer",
            name="Senior AI Software Engineer",
            description="Implements approved functionality and architecture components.",
            capabilities=("cap_code_gen", "cap_test_auto"),
            authority=_authority(can_write_code=True, can_create_pr=True),
            responsibilities=(
                "Generate implementation code from approved requirements.",
                "Create deterministic automated tests.",
                "Submit changes for independent review.",
            ),
        ),
        "role_code_reviewer": DashboardRoleTemplate(
            id="role_code_reviewer",
            name="Lead Code Reviewer & Security Gate",
            description="Reviews implementation evidence, security, and quality.",
            capabilities=("cap_code_review", "cap_gov_approve"),
            authority=_authority(can_approve_pr=True, can_reject_pr=True),
            responsibilities=(
                "Review proposed changes.",
                "Evaluate security and static-analysis evidence.",
                "Sign review artifacts.",
            ),
        ),
        "role_system_architect": DashboardRoleTemplate(
            id="role_system_architect",
            name="Principal System Architect",
            description="Owns system design and architecture decisions.",
            capabilities=("cap_arch_design", "cap_gov_approve"),
            authority=_authority(can_approve_architecture=True),
            responsibilities=(
                "Record architecture decisions.",
                "Verify cross-component compatibility.",
            ),
        ),
        "role_human_supervisor": DashboardRoleTemplate(
            id="role_human_supervisor",
            name="Executive Human Supervisor",
            description="Provides final human approval for governed releases.",
            capabilities=("cap_gov_approve",),
            authority=_authority(can_approve_to_prod=True),
            responsibilities=(
                "Evaluate critical governance gates.",
                "Approve production releases.",
            ),
        ),
    }
)
