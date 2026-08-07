"""Compile approved requirements + architecture into specialist-agent contracts.

This module is intentionally deterministic. It does not call an LLM, choose an
architecture, write files, or dispatch work. It compiles already-approved
contracts into bounded instructions for later specialist agents.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from domain.agent_contract import AgentContract, AgentContractPackage, AGENT_ROLES
from domain.architecture_contract import ArchitectureContract
from domain.requirements import RequirementsSpecification
from services.requirements_validator import validate_requirements


class ContractCompilationError(ValueError):
    """Raised when the contract graph is not safe to compile."""


@dataclass(frozen=True)
class CompilationResult:
    package: AgentContractPackage
    warnings: tuple[str, ...] = ()


_ROLE_DEFINITIONS = {
    "development": {
        "objective": "Implement only the approved architecture and requirements.",
        "inputs": ("requirements_contract", "architecture_contract", "approved_task"),
        "outputs": ("source_changes", "implementation_report", "traceability_updates"),
        "forbidden": ("inventing requirements", "changing architecture", "bypassing audit gates", "writing outside the assigned project boundary"),
        "instructions": ("Map every implementation change to a requirement or approved architecture decision.", "Preserve existing contracts unless an explicit change request is supplied.", "Return evidence for every completed acceptance criterion."),
    },
    "test": {
        "objective": "Prove the implementation against the approved contracts.",
        "inputs": ("requirements_contract", "architecture_contract", "implementation_artifact"),
        "outputs": ("tests", "test_report", "failure_evidence"),
        "forbidden": ("weakening requirements to make tests pass", "modifying production code without an approved task", "marking unverified behavior as passed"),
        "instructions": ("Turn acceptance criteria into executable tests where possible.", "Test architecture boundaries and negative cases, not only happy paths.", "Report failures with reproducible evidence."),
    },
    "audit": {
        "objective": "Independently determine whether the delivered artifact conforms to its contracts.",
        "inputs": ("requirements_contract", "architecture_contract", "implementation_artifact", "test_report"),
        "outputs": ("audit_report", "findings", "release_recommendation"),
        "forbidden": ("changing the artifact under audit", "waiving a blocking finding", "assuming undocumented behavior is compliant"),
        "instructions": ("Check traceability from requirements to implementation evidence.", "Check architecture boundaries and forbidden patterns.", "Separate evidence, findings and recommendations."),
    },
    "security": {
        "objective": "Assess security and privacy conformance against explicit contract constraints.",
        "inputs": ("requirements_contract", "architecture_contract", "implementation_artifact"),
        "outputs": ("security_report", "findings", "risk_rating"),
        "forbidden": ("inventing credentials", "disabling security controls", "treating missing evidence as safe"),
        "instructions": ("Evaluate every security and compliance requirement.", "Fail closed when required evidence is absent.", "Identify concrete attack or misuse paths and their evidence."),
    },
    "documentation": {
        "objective": "Produce documentation that reflects the approved system without inventing behavior.",
        "inputs": ("requirements_contract", "architecture_contract", "implementation_artifact", "audit_report"),
        "outputs": ("documentation", "traceability_summary"),
        "forbidden": ("inventing features", "changing contracts", "hiding audit findings"),
        "instructions": ("Document only behavior supported by contract or evidence.", "Preserve stable identifiers and fingerprints.", "Link claims to their source evidence."),
    },
    "project_management": {
        "objective": "Coordinate work against the approved contract graph and evidence state.",
        "inputs": ("requirements_contract", "architecture_contract", "agent_reports"),
        "outputs": ("task_plan", "status_report", "escalations"),
        "forbidden": ("changing requirements without human approval", "declaring completion without evidence", "overriding audit or security gates"),
        "instructions": ("Track work by stable contract identifiers.", "Escalate blocked or conflicting evidence.", "Treat approval and audit gates as authoritative state transitions."),
    },
    "distribution": {
        "objective": "Route an approved task to the correct specialist without altering its contract.",
        "inputs": ("requirements_contract", "architecture_contract", "agent_contract_package", "approved_task"),
        "outputs": ("dispatch_record", "selected_agent_contract", "handoff_record"),
        "forbidden": ("rewriting prompts", "selecting an unapproved agent role", "dispatching without required evidence", "bypassing gates"),
        "instructions": ("Select only from the compiled agent contracts.", "Pass the exact contract fingerprint with every handoff.", "Reject dispatch when required inputs are absent."),
    },
}


def compile_contracts(
    requirements: RequirementsSpecification,
    architecture: ArchitectureContract,
) -> CompilationResult:
    """Compile a deterministic agent contract package from approved inputs."""
    _assert_approved_requirements(requirements)
    _assert_approved_architecture(architecture)

    validation = validate_requirements(requirements)
    if not validation.valid:
        codes = ", ".join(issue.code for issue in validation.issues)
        raise ContractCompilationError(f"Requirements contract is not valid: {codes}")

    requirement_ids = tuple(item.id for item in requirements.all_items() if hasattr(item, "id"))
    contracts = tuple(
        _compile_agent(
            role,
            requirements.fingerprint,
            architecture.fingerprint,
            requirement_ids,
        )
        for role in AGENT_ROLES
    )
    package_id = _package_id(requirements.specification_id, requirements.version, architecture.contract_id, architecture.version)
    package = AgentContractPackage(
        schema_version="0.1",
        package_id=package_id,
        requirements_fingerprint=requirements.fingerprint,
        architecture_fingerprint=architecture.fingerprint,
        contracts=contracts,
    )
    return CompilationResult(package=package)


def _assert_approved_requirements(spec: RequirementsSpecification) -> None:
    if spec.status != "approved" or spec.approval.status != "approved":
        raise ContractCompilationError("Requirements must be human-approved before compilation")
    if spec.approval.content_fingerprint != spec.fingerprint:
        raise ContractCompilationError("Requirements approval fingerprint does not match content")


def _assert_approved_architecture(contract: ArchitectureContract) -> None:
    if contract.status != "approved" or not contract.human_approved_by or not contract.human_approved_at:
        raise ContractCompilationError("Architecture must be human-approved before compilation")


def _compile_agent(role: str, requirements_fp: str, architecture_fp: str, requirement_ids: tuple[str, ...]) -> AgentContract:
    definition = _ROLE_DEFINITIONS[role]
    return AgentContract(
        schema_version="0.1",
        contract_id=f"agent-{role}-v0.1",
        role=role,
        objective=definition["objective"],
        source_requirements_fingerprint=requirements_fp,
        source_architecture_fingerprint=architecture_fp,
        required_inputs=definition["inputs"],
        permitted_outputs=definition["outputs"],
        forbidden_actions=definition["forbidden"],
        acceptance_criteria_ids=requirement_ids,
        instructions=definition["instructions"],
    )


def _package_id(specification_id: str, requirements_version: str, architecture_id: str, architecture_version: str) -> str:
    payload = {
        "specification_id": specification_id,
        "requirements_version": requirements_version,
        "architecture_id": architecture_id,
        "architecture_version": architecture_version,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]
    return f"contract-package-{digest}"
