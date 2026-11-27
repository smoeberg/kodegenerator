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

Since decision 41 the split of modules into packages can come from the task
producer (an agent): ``split`` lists packages with a module, a description,
a weight, owned paths inside the module's own paths, the module's criteria
it carries and dependencies. The compiler is then the task producer's fact
check: every module covered, every criterion of a module in exactly one of
its packages, paths inside the module, dependencies known and acyclic. The
contract foundation is always package 0 and never part of the split.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
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
MAX_WEIGHT = 100
_PACKAGE_ID = re.compile(r"^module-[a-z0-9][a-z0-9-]{0,62}$")

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
    split: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile contracts into a work plan; fails closed on unsafe input.

    Without ``split`` every module is one package; with it, the task
    producer's split is validated and compiled (decision 41).
    """
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
    for entry in _module_packages(modules, contracts["acceptance_criteria"], split):
        task_id, module_id = entry["package_id"], entry["module_id"]
        try:
            scope = WriteScope(tuple(sorted(set(entry["owned_paths"]))))
        except ValueError as exc:
            raise TaskCompilerError(
                f"package {task_id} has an invalid write scope: {exc}"
            ) from exc
        if scope.overlaps(foundation_scope):
            raise TaskCompilerError(
                f"package {task_id} writes into {CONTRACT_ROOT}/, which belongs to the contract foundation"
            )
        specs.append(
            FactoryTaskSpec(
                logical_task_id=task_id,
                criterion_ids=tuple(entry["criterion_ids"]),
                required_checks=REQUIRED_CHECKS,
                write_scope=scope,
                dependency_ids=tuple(sorted({FOUNDATION_ID, *entry["depends_on"]})),
            )
        )
        packages[task_id] = {
            "task_type": entry["task_type"],
            "module_id": module_id,
            "description": entry["description"],
            "weight": entry["weight"],
            "requirement_ids": entry["requirement_ids"],
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
        "task_split": "task_producer" if split is not None else "compiler_default",
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


def _module_packages(
    modules: Sequence[Mapping[str, Any]],
    criteria: list[Mapping[str, Any]],
    split: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """The module packages: one per module, or the task producer's split, checked."""
    by_id = {str(m["module_id"]): m for m in modules}
    criterion_requirement = {str(c["id"]): c.get("requirement_id") for c in criteria}
    if split is None:
        return [
            {
                "package_id": f"module-{module_id}",
                "module_id": module_id,
                "description": f"Implement module {module_id} against its contract",
                "weight": _weight(module),
                "owned_paths": list(module.get("owned_paths") or []),
                "criterion_ids": _criteria_of(module, criteria),
                "depends_on": [],
                "task_type": _task_type(module),
                "requirement_ids": sorted(module.get("requirement_ids") or []),
            }
            for module_id, module in by_id.items()
        ]
    problems = check_split(split, modules, criteria)
    if problems:
        raise TaskCompilerError("; ".join(p["issue"] for p in problems))
    out = []
    for raw in split["packages"]:
        module = by_id[raw["module_id"]]
        out.append(
            {
                "package_id": raw["package_id"],
                "module_id": raw["module_id"],
                "description": raw["description"].strip(),
                "weight": int(raw["weight"]),
                "owned_paths": list(raw["owned_paths"]),
                "criterion_ids": sorted(raw["criterion_ids"]),
                "depends_on": list(raw.get("depends_on") or []),
                "task_type": _task_type(module),
                "requirement_ids": sorted(
                    {criterion_requirement[c] for c in raw["criterion_ids"]}
                    & set(module.get("requirement_ids") or [])
                )
                or sorted(module.get("requirement_ids") or []),
            }
        )
    return out


def _within(path: str, roots: Sequence[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def check_split(
    split: Mapping[str, Any],
    modules: Sequence[Mapping[str, Any]],
    criteria: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """The compiler as the task producer's fact check. No language model."""
    findings: list[dict[str, Any]] = []

    def finding(code: str, target: str, issue: str) -> None:
        findings.append(
            {
                "id": f"FC-{len(findings) + 1}",
                "code": code,
                "target": target,
                "issue": issue,
            }
        )

    by_id = {str(m["module_id"]): m for m in modules}
    packages = list(split.get("packages") or [])
    ids = [str(p.get("package_id")) for p in packages]
    for pid in sorted({i for i in ids if ids.count(i) > 1}):
        finding("duplicate_package", pid, f"package id {pid} is used twice")
    known = set(ids)
    seen: dict[str, dict[str, list[str]]] = {m: {} for m in by_id}
    for raw in packages:
        pid = str(raw.get("package_id"))
        module_id = str(raw.get("module_id"))
        if not _PACKAGE_ID.match(pid):
            finding("package_id", pid, f"{pid} must look like module-<name>")
        if module_id not in by_id:
            finding("unknown_module", pid, f"{pid} names unknown module {module_id}")
            continue
        module = by_id[module_id]
        if not str(raw.get("description") or "").strip():
            finding("no_description", pid, f"{pid} has no description")
        weight = raw.get("weight")
        if not isinstance(weight, int) or not 1 <= weight <= MAX_WEIGHT:
            finding("weight", pid, f"{pid} needs a weight from 1 to {MAX_WEIGHT}")
        roots = list(module.get("owned_paths") or [])
        paths = list(raw.get("owned_paths") or [])
        if not paths:
            finding("no_paths", pid, f"{pid} owns no paths")
        for path in paths:
            if not _within(str(path), roots):
                finding(
                    "path_outside_module",
                    pid,
                    f"{pid} owns {path}, outside module {module_id}'s paths {roots}",
                )
        own = set(_criteria_of(module, criteria))
        for criterion in raw.get("criterion_ids") or []:
            if criterion not in own:
                finding(
                    "foreign_criterion",
                    pid,
                    f"{pid} carries {criterion}, which is not a criterion of module {module_id}",
                )
            else:
                seen[module_id].setdefault(criterion, []).append(pid)
        if not raw.get("criterion_ids"):
            finding("no_criteria", pid, f"{pid} carries no acceptance criterion")
        for dep in raw.get("depends_on") or []:
            if dep != FOUNDATION_ID and dep not in known:
                finding(
                    "unknown_dependency", pid, f"{pid} depends on unknown package {dep}"
                )
    for module_id, module in by_id.items():
        if not any(str(p.get("module_id")) == module_id for p in packages):
            finding(
                "module_not_covered", module_id, f"module {module_id} has no package"
            )
            continue
        for criterion in _criteria_of(module, criteria):
            holders = seen[module_id].get(criterion, [])
            if len(holders) != 1:
                finding(
                    "criterion_coverage",
                    module_id,
                    f"criterion {criterion} of module {module_id} is in {len(holders)} packages, must be in exactly one",
                )
    return findings


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
