"""Task compiler: completion plan step 5.

Turns approved module contracts into work packages, day sprints, a critical
path and a scaling plan for the project manager to approve. The task
compiler is a system role in the role-process catalog: deterministic, no
language model, controlled by the project manager.

The foundation is code, not text (plan, "Første gennemløb"):

* package 0, the **contract foundation**, writes the interfaces, types and
  contract tests of every module into its own area (``contracts/``) before
  any module is coded;
* every module is one package that depends on the foundation only. Modules
  build against the contracts, not against each other's code, so they can
  run in parallel; integration is tested on the milestone as a whole.

Packages are validated through ``FactoryTaskSynthesizer``, which adds a
dependency wherever write scopes overlap and rejects cycles.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from domain.factory_work import ExecutionMode, WriteScope
from execution.factory_task_synthesizer import FactoryTaskSpec, FactoryTaskSynthesizer

#: Version of the task-type vocabulary. Task types are what agent statistics
#: compare on (plan, "Agentstatistik"), so the vocabulary is versioned.
TASK_TYPES_VERSION = 1
TASK_TYPES = ("contract_foundation", "module_http", "module_service", "module_data")

CONTRACT_ROOT = "contracts"
FOUNDATION_ID = "contract-foundation"

#: Checks every package must pass before it is merged (house rules v1).
REQUIRED_CHECKS = (
    "coverage",
    "fact_check",
    "format",
    "level1",
    "level2",
    "lint",
    "security",
    "tests",
)


class TaskCompilerError(ValueError):
    """Contracts that cannot be compiled into safe parallel work."""


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode()
    ).hexdigest()


def _task_type(module: Mapping[str, Any]) -> str:
    kinds = {str(i.get("kind")) for i in module.get("provides") or []}
    if "http" in kinds:
        return "module_http"
    if kinds:
        return "module_service"
    return "module_data"


def _operations(module: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        op for i in module.get("provides") or [] for op in i.get("operations") or []
    ]


def _criteria_of(
    module: Mapping[str, Any], criteria: list[Mapping[str, Any]]
) -> list[str]:
    """Criteria the module's operations carry; for a module without operations,
    the criteria of the requirements it covers."""
    carried = {
        c for op in _operations(module) for c in op.get("acceptance_criteria") or []
    }
    if carried:
        return sorted(carried)
    covered = set(module.get("requirement_ids") or [])
    return sorted(str(c["id"]) for c in criteria if c.get("requirement_id") in covered)


def _weight(module: Mapping[str, Any]) -> int:
    """Relative effort: operations plus data entities, at least one."""
    return max(1, len(_operations(module)) + len(module.get("data") or []))


def compile_work_plan(
    contracts: Mapping[str, Any],
    *,
    workflow_id: str,
    organization_id: str,
    contract_fingerprint: str,
    architecture_fingerprint: str,
    requirements_fingerprint: str,
    milestone_id: str = "M1",
    max_parallel_packages: int | None = None,
) -> dict[str, Any]:
    """Compile contracts into a work plan; fails closed on unsafe input."""
    modules = list(contracts.get("modules") or [])
    if not modules:
        raise TaskCompilerError("contracts have no modules")
    if not contracts.get("acceptance_criteria"):
        raise TaskCompilerError("contracts have no acceptance criteria")
    if max_parallel_packages is not None and max_parallel_packages < 1:
        raise TaskCompilerError("max_parallel_packages must be at least 1")

    foundation_scope = WriteScope((CONTRACT_ROOT,))
    specs = [
        FactoryTaskSpec(
            logical_task_id=FOUNDATION_ID,
            # The foundation writes a contract test for every criterion
            # (house rule 3.4); modules carry their own as implementation.
            criterion_ids=tuple(
                sorted(
                    {str(c["id"]) for c in contracts.get("acceptance_criteria") or []}
                )
            ),
            required_checks=REQUIRED_CHECKS,
            write_scope=foundation_scope,
        )
    ]
    packages: dict[str, dict[str, Any]] = {
        FOUNDATION_ID: {
            "task_type": "contract_foundation",
            "module_id": None,
            "description": "Interfaces, types and contract tests for every module",
            "weight": len(modules),
            "requirement_ids": sorted(
                {r for m in modules for r in m.get("requirement_ids") or []}
            ),
        }
    }
    for module in modules:
        module_id = str(module["module_id"])
        task_id = f"module-{module_id}"
        try:
            scope = WriteScope(tuple(sorted(set(module.get("owned_paths") or []))))
        except ValueError as exc:
            raise TaskCompilerError(
                f"module {module_id} has an invalid write scope: {exc}"
            ) from exc
        if scope.overlaps(foundation_scope):
            raise TaskCompilerError(
                f"module {module_id} writes into {CONTRACT_ROOT}/, which belongs to the contract foundation"
            )
        specs.append(
            FactoryTaskSpec(
                logical_task_id=task_id,
                criterion_ids=tuple(
                    _criteria_of(module, contracts["acceptance_criteria"])
                ),
                required_checks=REQUIRED_CHECKS,
                write_scope=scope,
                dependency_ids=(FOUNDATION_ID,),
            )
        )
        packages[task_id] = {
            "task_type": _task_type(module),
            "module_id": module_id,
            "description": f"Implement module {module_id} against its contract",
            "weight": _weight(module),
            "requirement_ids": sorted(module.get("requirement_ids") or []),
        }

    # Validation and overlap-induced dependencies by the existing synthesizer.
    try:
        synthesized = FactoryTaskSynthesizer().synthesize(
            organization_id=organization_id,
            workflow_id=workflow_id,
            requirements_fingerprint=requirements_fingerprint,
            architecture_fingerprint=architecture_fingerprint,
            contract_fingerprint=contract_fingerprint,
            base_sha="0" * 40,
            tasks=tuple(specs),
            execution_mode=ExecutionMode.SINGLE,
            candidate_count=1,
            allocation_id="plan",
            allocation_version=1,
            policy_fingerprint="0" * 64,
            token_budget=1,
            time_budget_seconds=1,
        )
    except ValueError as exc:
        raise TaskCompilerError(f"work packages are not consistent: {exc}") from exc

    dependencies = {p.logical_task_id: tuple(p.dependency_ids) for p in synthesized}
    for package in synthesized:
        packages[package.logical_task_id].update(
            {
                "work_package_id": package.work_package_id,
                "dependency_ids": list(package.dependency_ids),
                "criterion_ids": list(package.criterion_ids),
                "required_checks": list(package.required_checks),
                "write_scope": {
                    key: list(value)
                    for key, value in asdict(package.write_scope).items()
                },
            }
        )

    layers = _layers(dependencies)
    sprints = _sprints(layers, max_parallel_packages)
    critical_path, critical_weight = _critical_path(
        dependencies, {k: v["weight"] for k, v in packages.items()}
    )
    for sprint in sprints:
        for task_id in sprint["packages"]:
            packages[task_id]["sprint"] = sprint["sprint"]
    widest = max(len(s["packages"]) for s in sprints)
    plan = {
        "milestone_id": milestone_id,
        "task_types_version": TASK_TYPES_VERSION,
        "contract_fingerprint": contract_fingerprint,
        "packages": [
            {"logical_task_id": k, **v}
            for k, v in sorted(
                packages.items(), key=lambda kv: (kv[1]["sprint"], kv[0])
            )
        ],
        "sprints": sprints,
        "critical_path": critical_path,
        "scaling_plan": {
            "sprints": len(sprints),
            "parallel_packages_max": widest,
            "parallel_agents_per_role": {
                "coder": widest,
                "code_auditor": widest,
                "context_controller": widest,
            },
            "critical_path_weight": critical_weight,
            "total_weight": sum(v["weight"] for v in packages.values()),
            "max_parallel_packages": max_parallel_packages,
            "status": "awaiting_approval",
        },
    }
    plan["fingerprint"] = _fingerprint(
        {k: v for k, v in plan.items() if k != "fingerprint"}
    )
    return plan


def _layers(dependencies: Mapping[str, tuple[str, ...]]) -> list[list[str]]:
    layers: list[list[str]] = []
    done: set[str] = set()
    while len(done) < len(dependencies):
        layer = sorted(
            t for t, deps in dependencies.items() if t not in done and set(deps) <= done
        )
        if not layer:
            raise TaskCompilerError("work package dependencies contain a cycle")
        layers.append(layer)
        done.update(layer)
    return layers


def _sprints(layers: list[list[str]], limit: int | None) -> list[dict[str, Any]]:
    """Day sprints: one dependency layer per sprint, split if above the limit."""
    sprints: list[dict[str, Any]] = []
    for layer in layers:
        chunk = limit or len(layer)
        for start in range(0, len(layer), chunk):
            sprints.append(
                {"sprint": len(sprints) + 1, "packages": layer[start : start + chunk]}
            )
    return sprints


def _critical_path(
    dependencies: Mapping[str, tuple[str, ...]], weights: Mapping[str, int]
) -> tuple[list[str], int]:
    """Longest weighted dependency chain: a lower bound on time, whatever the agent count."""
    best: dict[str, tuple[int, list[str]]] = {}
    for layer in _layers(dependencies):
        for task in layer:
            predecessors = [best[d] for d in dependencies[task]]
            base = max(predecessors, key=lambda item: item[0], default=(0, []))
            best[task] = (base[0] + weights[task], [*base[1], task])
    weight, path = max(best.values(), key=lambda item: (item[0], item[1]))
    return path, weight
