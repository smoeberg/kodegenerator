"""Deterministic routing contracts for P3-19.

Distribution is a transport boundary, not an AI decision-maker. It may select
only an already compiled specialist contract from an approved package and
must preserve the package and contract fingerprints verbatim.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Mapping

from domain.agent_contract import AgentContract, AgentContractPackage


class DistributionError(ValueError):
    """Raised when a dispatch cannot be proven contract-safe."""


@dataclass(frozen=True)
class DispatchRequest:
    package_fingerprint: str
    role: str
    available_inputs: tuple[str, ...]
    task_id: str
    task_fingerprint: str

    def __post_init__(self) -> None:
        for name, value in (
            ("package_fingerprint", self.package_fingerprint),
            ("role", self.role),
            ("task_id", self.task_id),
            ("task_fingerprint", self.task_fingerprint),
        ):
            if not isinstance(value, str) or not value.strip():
                raise DistributionError(f"{name} must be non-empty")
        if not self.available_inputs:
            raise DistributionError("available_inputs must not be empty")
        if len(self.available_inputs) != len(set(self.available_inputs)):
            raise DistributionError("available_inputs must be unique")


@dataclass(frozen=True)
class DispatchRecord:
    schema_version: str
    dispatch_id: str
    task_id: str
    task_fingerprint: str
    package_id: str
    package_fingerprint: str
    selected_role: str
    contract_id: str
    contract_fingerprint: str
    required_inputs: tuple[str, ...]
    permitted_outputs: tuple[str, ...]

    @property
    def fingerprint(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "dispatch_id": self.dispatch_id,
            "task_id": self.task_id,
            "task_fingerprint": self.task_fingerprint,
            "package_id": self.package_id,
            "package_fingerprint": self.package_fingerprint,
            "selected_role": self.selected_role,
            "contract_id": self.contract_id,
            "contract_fingerprint": self.contract_fingerprint,
            "required_inputs": list(self.required_inputs),
            "permitted_outputs": list(self.permitted_outputs),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def route(package: AgentContractPackage, request: DispatchRequest) -> DispatchRecord:
    """Create a deterministic dispatch record from an immutable contract package."""
    if request.package_fingerprint != package.fingerprint:
        raise DistributionError("Package fingerprint does not match dispatch request")

    contract = _select_contract(package, request.role)
    missing = tuple(item for item in contract.required_inputs if item not in request.available_inputs)
    if missing:
        raise DistributionError("Required dispatch inputs are missing: " + ", ".join(missing))

    dispatch_id = _dispatch_id(request, contract)
    return DispatchRecord(
        schema_version="0.1",
        dispatch_id=dispatch_id,
        task_id=request.task_id,
        task_fingerprint=request.task_fingerprint,
        package_id=package.package_id,
        package_fingerprint=package.fingerprint,
        selected_role=contract.role,
        contract_id=contract.contract_id,
        contract_fingerprint=contract.fingerprint,
        required_inputs=contract.required_inputs,
        permitted_outputs=contract.permitted_outputs,
    )


def _select_contract(package: AgentContractPackage, role: str) -> AgentContract:
    matches = tuple(contract for contract in package.contracts if contract.role == role)
    if len(matches) != 1:
        raise DistributionError(f"Package does not contain exactly one contract for role: {role}")
    return matches[0]


def _dispatch_id(request: DispatchRequest, contract: AgentContract) -> str:
    payload: Mapping[str, str] = {
        "task_id": request.task_id,
        "task_fingerprint": request.task_fingerprint,
        "package_fingerprint": request.package_fingerprint,
        "contract_fingerprint": contract.fingerprint,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "dispatch-" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]
