"""Compile approved contract tasks into a deterministic factory DAG."""

from __future__ import annotations

from dataclasses import dataclass

from domain.factory_work import (
    ExecutionMode,
    WorkPackage,
    WorkPackageStatus,
    WriteScope,
    fingerprint,
)


class WriteScopeConflictError(ValueError):
    pass


@dataclass(frozen=True)
class FactoryTaskSpec:
    logical_task_id: str
    criterion_ids: tuple[str, ...]
    required_checks: tuple[str, ...]
    write_scope: WriteScope
    dependency_ids: tuple[str, ...] = ()


class FactoryTaskSynthesizer:
    def synthesize(
        self,
        *,
        organization_id: str,
        workflow_id: str,
        requirements_fingerprint: str,
        architecture_fingerprint: str,
        contract_fingerprint: str,
        base_sha: str,
        tasks: tuple[FactoryTaskSpec, ...],
        execution_mode: ExecutionMode,
        candidate_count: int,
        allocation_id: str,
        allocation_version: int,
        policy_fingerprint: str,
        token_budget: int,
        time_budget_seconds: int,
    ) -> tuple[WorkPackage, ...]:
        if not tasks or len({task.logical_task_id for task in tasks}) != len(tasks):
            raise ValueError("task specifications must be non-empty and unique")
        known = {task.logical_task_id for task in tasks}
        normalized: list[FactoryTaskSpec] = []
        for task in sorted(tasks, key=lambda item: item.logical_task_id):
            missing = set(task.dependency_ids) - known
            if missing or task.logical_task_id in task.dependency_ids:
                raise ValueError("task dependency graph contains an invalid reference")
            dependencies = set(task.dependency_ids)
            for earlier in normalized:
                if task.write_scope.overlaps(earlier.write_scope):
                    dependencies.add(earlier.logical_task_id)
            normalized.append(
                FactoryTaskSpec(
                    task.logical_task_id,
                    task.criterion_ids,
                    task.required_checks,
                    task.write_scope,
                    tuple(sorted(dependencies)),
                )
            )
        self._verify_acyclic(tuple(normalized))
        packages = []
        for task in normalized:
            package_id = fingerprint(
                {
                    "workflow_id": workflow_id,
                    "task": task.logical_task_id,
                    "contract": contract_fingerprint,
                }
            )
            packages.append(
                WorkPackage(
                    organization_id=organization_id,
                    work_package_id=package_id,
                    logical_task_id=task.logical_task_id,
                    workflow_id=workflow_id,
                    requirements_fingerprint=requirements_fingerprint,
                    architecture_fingerprint=architecture_fingerprint,
                    contract_fingerprint=contract_fingerprint,
                    base_sha=base_sha,
                    dependency_ids=task.dependency_ids,
                    criterion_ids=tuple(sorted(task.criterion_ids)),
                    required_checks=tuple(sorted(task.required_checks)),
                    write_scope=task.write_scope,
                    execution_mode=execution_mode,
                    candidate_count=candidate_count,
                    allocation_id=allocation_id,
                    allocation_version=allocation_version,
                    policy_fingerprint=policy_fingerprint,
                    token_budget=token_budget,
                    time_budget_seconds=time_budget_seconds,
                    idempotency_key=f"factory:{workflow_id}:{package_id}",
                    status=WorkPackageStatus.READY
                    if not task.dependency_ids
                    else WorkPackageStatus.BLOCKED,
                )
            )
        return tuple(packages)

    @staticmethod
    def _verify_acyclic(tasks: tuple[FactoryTaskSpec, ...]) -> None:
        graph = {task.logical_task_id: set(task.dependency_ids) for task in tasks}
        pending = set(graph)
        while pending:
            ready = {item for item in pending if not (graph[item] & pending)}
            if not ready:
                raise ValueError("task dependency graph contains a cycle")
            pending -= ready
