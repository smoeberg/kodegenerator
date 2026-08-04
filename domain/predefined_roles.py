"""Prædefinerede organisatoriske Roller og Capabilities i Digital Organization Runtime (DOR)."""

from typing import Dict, List
from domain.role_definition import RoleDefinition
from domain.capability import Capability, CapabilityLevel

# Standard Capabilities i DOR
STANDARD_CAPABILITIES: Dict[str, Capability] = {
    "code_generation": Capability(
        id="cap_code_gen",
        name="Code Generation",
        description="Evnen til at skrive funktionel kildekode ud fra kravspecifikationer.",
        level=CapabilityLevel.EXPERT
    ),
    "code_review": Capability(
        id="cap_code_review",
        name="Code Review & Quality Gate",
        description="Evnen til at gennemgå kildekode for fejl, sikkerhedshuller og kodestandarder.",
        level=CapabilityLevel.EXPERT
    ),
    "architecture_design": Capability(
        id="cap_arch_design",
        name="System Architecture & ADR",
        description="Evnen til at designe distribuerede systemer og udarbejde Architecture Decision Records.",
        level=CapabilityLevel.ADVANCED
    ),
    "test_automation": Capability(
        id="cap_test_auto",
        name="Automated Testing (pytest/E2E)",
        description="Evnen til at skrive og afvikle automatiserede enheds- og integrationstests.",
        level=CapabilityLevel.ADVANCED
    ),
    "governance_approval": Capability(
        id="cap_gov_approve",
        name="Governance Gate Sign-off",
        description="Autoritet til at godkende ændringer til produktion eller arkitektur.",
        level=CapabilityLevel.EXPERT
    )
}

# Standard Roller i DOR med klare ansvarsområder og autoriteter
STANDARD_ROLES: Dict[str, RoleDefinition] = {
    "role_senior_developer": RoleDefinition(
        id="role_senior_developer",
        name="Senior AI Software Engineer",
        description="Ansvarlig for implementering af funktionalitet og arkitekturkomponenter.",
        capabilities=["cap_code_gen", "cap_test_auto"],
        authority={
            "can_write_code": True,
            "can_create_pr": True,
            "can_approve_to_prod": False
        },
        responsibilities=[
            "Generere højkvalitets kildekode baseret på godkendte kravartefakter.",
            "Skrive automatiserede enhedstests.",
            "Indsende Pull Requests til Code Reviewer."
        ]
    ),
    "role_code_reviewer": RoleDefinition(
        id="role_code_reviewer",
        name="Lead Code Reviewer & Security Gate",
        description="Ansvarlig for auditering af kildekode, sikkerhedstjek og signering af kvalitetsevalueringer.",
        capabilities=["cap_code_review", "cap_gov_approve"],
        authority={
            "can_approve_pr": True,
            "can_reject_pr": True,
            "can_sign_artifact": True,
            "can_approve_to_prod": False
        },
        responsibilities=[
            "Gennemgå Pull Requests genereret af udviklere.",
            "Køre og evaluere sikkerhedsscanninger og statisk kodeanalyse.",
            "Signere Artifacts med godkendelse eller ændringsønsker."
        ]
    ),
    "role_system_architect": RoleDefinition(
        id="role_system_architect",
        name="Principal System Architect",
        description="Ansvarlig for overordnet systemdesign og oprettelse af arkitekturspecifikationer.",
        capabilities=["cap_arch_design", "cap_gov_approve"],
        authority={
            "can_approve_architecture": True,
            "can_override_design": True
        },
        responsibilities=[
            "Udarbejde Architecture Decision Records (ADR).",
            "Sikre systemkompatibilitet på tværs af mikrotjenester."
        ]
    ),
    "role_human_supervisor": RoleDefinition(
        id="role_human_supervisor",
        name="Executive Human Supervisor",
        description="Menneskelig leder med ultimativ autoritet til at frigive til produktion og ændre organisatorisk governance.",
        capabilities=["cap_gov_approve"],
        authority={
            "can_approve_to_prod": True,
            "can_override_all": True
        },
        responsibilities=[
            "Evaluere kritiske Governance Gates.",
            "Udføre endelig godkendelse af produktions-releases."
        ]
    )
}
