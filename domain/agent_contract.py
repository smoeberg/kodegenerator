"""Deterministic contracts consumed by specialist software agents."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any


class AgentContractError(ValueError):
    """Raised when an executable agent contract is invalid."""


AGENT_ROLES = (
    "development",
    "test",
    "audit",
    "security",
    "documentation",
    "project_management",
    "distribution",
)


@dataclass(frozen=True)
class AgentContract:
    schema_version: str
    contract_id: str
    role: str
    objective: str
    source_requirements_fingerprint: str
    source_architecture_fingerprint: str
    required_inputs: tuple[str, ...]
    permitted_outputs: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    acceptance_criteria_ids: tuple[str, ...]
    instructions: tuple[str, ...]

    def __post_init__(self) -> None:
        for name, value in (("schema_version", self.schema_version), ("contract_id", self.contract_id),
                            ("objective", self.objective), ("source_requirements_fingerprint", self.source_requirements_fingerprint),
                            ("source_architecture_fingerprint", self.source_architecture_fingerprint)):
            if not isinstance(value, str) or not value.strip():
                raise AgentContractError(f"{name} must be non-empty")
        if self.role not in AGENT_ROLES:
            raise AgentContractError(f"Unsupported agent role: {self.role}")
        if not self.required_inputs or not self.permitted_outputs or not self.forbidden_actions:
            raise AgentContractError("Agent contracts require explicit inputs, outputs and forbidden actions")
        if not self.instructions:
            raise AgentContractError("Agent contract requires deterministic instructions")

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "contract_id": self.contract_id,
            "role": self.role,
            "objective": self.objective,
            "source_requirements_fingerprint": self.source_requirements_fingerprint,
            "source_architecture_fingerprint": self.source_architecture_fingerprint,
            "required_inputs": list(self.required_inputs),
            "permitted_outputs": list(self.permitted_outputs),
            "forbidden_actions": list(self.forbidden_actions),
            "acceptance_criteria_ids": list(self.acceptance_criteria_ids),
            "instructions": list(self.instructions),
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(self.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def system_prompt(self) -> str:
        """Render the exact deterministic system prompt supplied to an agent."""
        sections = [
            "You are a contract-bound specialist agent.",
            f"ROLE: {self.role}",
            f"OBJECTIVE: {self.objective}",
            f"REQUIREMENTS CONTRACT: {self.source_requirements_fingerprint}",
            f"ARCHITECTURE CONTRACT: {self.source_architecture_fingerprint}",
            "REQUIRED INPUTS:\n- " + "\n- ".join(self.required_inputs),
            "PERMITTED OUTPUTS:\n- " + "\n- ".join(self.permitted_outputs),
            "FORBIDDEN ACTIONS:\n- " + "\n- ".join(self.forbidden_actions),
            "ACCEPTANCE CRITERIA:\n- " + ("\n- ".join(self.acceptance_criteria_ids) if self.acceptance_criteria_ids else "None"),
            "INSTRUCTIONS:\n- " + "\n- ".join(self.instructions),
            f"CONTRACT FINGERPRINT: {self.fingerprint}",
        ]
        return "\n\n".join(sections)


@dataclass(frozen=True)
class AgentContractPackage:
    schema_version: str
    package_id: str
    requirements_fingerprint: str
    architecture_fingerprint: str
    contracts: tuple[AgentContract, ...]

    def __post_init__(self) -> None:
        if not self.contracts:
            raise AgentContractError("Contract package cannot be empty")
        roles = tuple(contract.role for contract in self.contracts)
        if len(roles) != len(set(roles)):
            raise AgentContractError("Each agent role may occur only once in a package")
        if any(contract.source_requirements_fingerprint != self.requirements_fingerprint for contract in self.contracts):
            raise AgentContractError("All agent contracts must bind the same requirements fingerprint")
        if any(contract.source_architecture_fingerprint != self.architecture_fingerprint for contract in self.contracts):
            raise AgentContractError("All agent contracts must bind the same architecture fingerprint")

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "requirements_fingerprint": self.requirements_fingerprint,
            "architecture_fingerprint": self.architecture_fingerprint,
            "contracts": [contract.fingerprint for contract in self.contracts],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
