"""Generate deterministic OpenAPI contracts from explicit HTTP criteria."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from generation.requirement_analysis import RequirementAnalysis, http_expectation


@dataclass(frozen=True)
class GeneratedContracts:
    openapi: dict
    traceability: tuple[dict[str, str], ...]
    fingerprint: str


class ContractGenerator:
    """Compile explicit acceptance criteria into an OpenAPI contract."""

    def generate(self, analysis: RequirementAnalysis) -> GeneratedContracts:
        paths: dict = {}
        traceability: list[dict[str, str]] = []
        for criterion in analysis.criteria:
            expectation = http_expectation(criterion.statement)
            if expectation is None:
                continue
            method, path, status = expectation
            operation_id = criterion.criterion_id.lower().replace("-", "_")
            paths.setdefault(path, {})[method.lower()] = {
                "operationId": operation_id,
                "responses": {str(status): {"description": criterion.statement}},
                "x-requirement-id": criterion.requirement_id,
                "x-criterion-id": criterion.criterion_id,
            }
            traceability.append(
                {
                    "criterion_id": criterion.criterion_id,
                    "requirement_id": criterion.requirement_id,
                    "operation_id": operation_id,
                }
            )
        if not paths:
            raise ValueError("no explicit HTTP expectations found in requirements")
        openapi = {
            "openapi": "3.1.0",
            "info": {"title": analysis.project_name, "version": "0.1.0"},
            "paths": paths,
        }
        encoded = json.dumps(openapi, sort_keys=True, separators=(",", ":"))
        return GeneratedContracts(
            openapi,
            tuple(traceability),
            hashlib.sha256(encoded.encode()).hexdigest(),
        )
