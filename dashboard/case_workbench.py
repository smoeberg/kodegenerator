"""Shared workbench projection for DOR / Guide.

This module binds backend-owned projects and executions into the canonical
CaseProcessProjection without inventing provenance. Only an explicit
execution.project_id relation is used. The resulting snapshot is presentation-
only and is intended to feed Sag, Mit arbejde and Overblik consistently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from dashboard.case_process_projection import (
    AttentionState,
    CaseProcessProjection,
    project_case,
)


@dataclass(frozen=True)
class CaseWorkbenchItem:
    projection: CaseProcessProjection
    project: dict[str, Any]
    execution: dict[str, Any] | None
    linked_execution_count: int


@dataclass(frozen=True)
class CaseWorkbenchSnapshot:
    cases: tuple[CaseWorkbenchItem, ...]
    unlinked_executions: tuple[dict[str, Any], ...]

    @property
    def requiring_action(self) -> tuple[CaseWorkbenchItem, ...]:
        return tuple(
            item
            for item in self.cases
            if item.projection.attention_required
            and item.projection.owner_type == "human"
        )

    @property
    def waiting_for_dor(self) -> tuple[CaseWorkbenchItem, ...]:
        return tuple(
            item for item in self.cases if item.projection.owner_type == "dor"
        )

    @property
    def waiting_external(self) -> tuple[CaseWorkbenchItem, ...]:
        return tuple(
            item for item in self.cases if item.projection.owner_type == "external"
        )

    @property
    def completed(self) -> tuple[CaseWorkbenchItem, ...]:
        terminal = {
            AttentionState.COMPLETED,
            AttentionState.CANCELLED,
            AttentionState.ARCHIVED,
        }
        return tuple(
            item
            for item in self.cases
            if item.projection.attention_state in terminal
        )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _project_id(project: Mapping[str, Any]) -> str:
    return _text(project.get("project_id") or project.get("id"))


def _execution_project_id(execution: Mapping[str, Any]) -> str:
    return _text(execution.get("project_id"))


def _execution_order_key(execution: Mapping[str, Any]) -> tuple[str, str]:
    """Deterministically prefer the newest backend snapshot for a project."""
    return (
        _text(execution.get("updated_at") or execution.get("created_at")),
        _text(execution.get("workflow_id")),
    )


def _case_sort_key(item: CaseWorkbenchItem) -> tuple[int, str, str]:
    """Attention first, then stable human title and case id."""
    state = item.projection.attention_state
    priority = {
        AttentionState.NEEDS_DECISION: 0,
        AttentionState.NEEDS_REVIEW: 1,
        AttentionState.NEEDS_INPUT: 2,
        AttentionState.BLOCKED: 3,
        AttentionState.FAILED: 4,
        AttentionState.READY: 5,
        AttentionState.REWORK_IN_PROGRESS: 6,
        AttentionState.DOR_WORKING: 7,
        AttentionState.WAITING_EXTERNAL: 8,
        AttentionState.COMPLETED: 9,
        AttentionState.CANCELLED: 10,
        AttentionState.ARCHIVED: 11,
    }.get(state, 99)
    return (
        priority,
        item.projection.title.casefold(),
        item.projection.case_id,
    )


def build_case_workbench(
    projects: Iterable[Mapping[str, Any]],
    executions: Iterable[Mapping[str, Any]],
) -> CaseWorkbenchSnapshot:
    """Build one shared presentation snapshot from backend project/execution data.

    No name matching, workflow-name matching or guessed provenance is permitted.
    Executions without an explicit project_id are returned separately so the UI can
    expose them only through specialist/recovery surfaces instead of inventing a Sag.
    """
    project_rows = [dict(project) for project in projects if isinstance(project, Mapping)]
    execution_rows = [
        dict(execution) for execution in executions if isinstance(execution, Mapping)
    ]

    by_project: dict[str, list[dict[str, Any]]] = {}
    unlinked: list[dict[str, Any]] = []
    known_project_ids = {
        project_id for project in project_rows if (project_id := _project_id(project))
    }

    for execution in execution_rows:
        project_id = _execution_project_id(execution)
        if not project_id or project_id not in known_project_ids:
            unlinked.append(execution)
            continue
        by_project.setdefault(project_id, []).append(execution)

    items: list[CaseWorkbenchItem] = []
    for project in project_rows:
        project_id = _project_id(project)
        if not project_id:
            # A backend project without identity cannot safely become a user-facing case.
            continue
        linked = sorted(
            by_project.get(project_id, []),
            key=_execution_order_key,
            reverse=True,
        )
        execution = linked[0] if linked else None
        projection = project_case(
            case_id=project_id,
            project_data=project,
            execution_data=execution,
        )
        items.append(
            CaseWorkbenchItem(
                projection=projection,
                project=project,
                execution=execution,
                linked_execution_count=len(linked),
            )
        )

    items.sort(key=_case_sort_key)
    unlinked.sort(key=_execution_order_key, reverse=True)
    return CaseWorkbenchSnapshot(cases=tuple(items), unlinked_executions=tuple(unlinked))


def overview_counts(snapshot: CaseWorkbenchSnapshot) -> dict[str, int]:
    """Counts used by Overblik, derived from the same cases as all other views."""
    return {
        "cases": len(snapshot.cases),
        "requires_action": len(snapshot.requiring_action),
        "waiting_for_dor": len(snapshot.waiting_for_dor),
        "waiting_external": len(snapshot.waiting_external),
        "completed": len(snapshot.completed),
        "unlinked_executions": len(snapshot.unlinked_executions),
    }


def find_case(
    snapshot: CaseWorkbenchSnapshot, case_id: str | None
) -> CaseWorkbenchItem | None:
    """Resolve a selected case by canonical case/project identity."""
    wanted = _text(case_id)
    if not wanted:
        return None
    return next(
        (item for item in snapshot.cases if item.projection.case_id == wanted),
        None,
    )
