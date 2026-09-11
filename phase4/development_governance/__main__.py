"""Canonical executable entrypoint: ``python -m phase4.development_governance``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import Any

from services.governed_llm import GovernedLLMRuntime
from services.llm_adapters import OpenAIAdapter

from .bootstrap import (
    GovernanceBootstrap,
    GovernanceBootstrapError,
    GovernanceProviderRegistry,
    RoleBinding,
    config_from_dict,
    governed_execution_factory,
    governed_llm_factory,
)
from .contracts import ProblemBrief


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _encode(asdict(value))
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_encode(item) for item in value]
    return value


def _runtime(binding: RoleBinding) -> GovernedLLMRuntime:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise GovernanceBootstrapError("OPENAI_API_KEY is required for governed_llm providers")
    return GovernedLLMRuntime(OpenAIAdapter(api_key=api_key, model=binding.model, max_retries=2,
                                             timeout_seconds=60, max_output_tokens=8_000))


def _problem(raw: Any) -> ProblemBrief:
    if not isinstance(raw, dict):
        raise GovernanceBootstrapError("problem input must be a JSON object")
    expected = {"problem_id", "version", "title", "observed_problem", "impact", "evidence_refs",
                "affected_concepts", "constraints", "non_goals", "proposed_scope"}
    if set(raw) != expected:
        raise GovernanceBootstrapError("problem fields do not match ProblemBrief contract")
    return ProblemBrief(raw["problem_id"], raw["version"], raw["title"], raw["observed_problem"], raw["impact"],
                        tuple(raw["evidence_refs"]), tuple(raw["affected_concepts"]), tuple(raw["constraints"]),
                        tuple(raw["non_goals"]), tuple(raw["proposed_scope"]))


def production_registry(
    config: Any,
    *,
    runtime_builder: Callable[[Path, Callable[[object], object]], tuple[object, object]] | None = None,
) -> GovernanceProviderRegistry:
    """Compose production roles from the configured existing runtime seams."""
    if runtime_builder is None:
        from api.dependencies import build_governance_implementation_runtimes

        runtime_builder = build_governance_implementation_runtimes
    return GovernanceProviderRegistry({
        "governed_llm": governed_llm_factory(_runtime),
        "governed_execution": governed_execution_factory(
            runtime_builder,
            repository_root=config.repository_root,
            base_sha=config.base_sha,
            project_id=os.getenv("DOR_GOVERNANCE_PROJECT_ID") or None,
            plan_fingerprint=os.getenv("DOR_GOVERNANCE_PLAN_FINGERPRINT") or None,
        ),
    })


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the canonical DOR Governance v0 coordinator")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--problem", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = config_from_dict(json.loads(args.config.read_text(encoding="utf-8")))
        problem = _problem(json.loads(args.problem.read_text(encoding="utf-8")))
        registry = production_registry(config)
        bootstrap = GovernanceBootstrap(config, registry)
        result = bootstrap.run(problem)
        print(json.dumps({"result": _encode(result), "audit": json.loads(bootstrap.audit.to_json())},
                         sort_keys=True, separators=(",", ":"), ensure_ascii=False))
        return 0 if result.review.decision.value == "APPROVED" else 1
    except (OSError, ValueError, TypeError, GovernanceBootstrapError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__},
                         sort_keys=True, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
