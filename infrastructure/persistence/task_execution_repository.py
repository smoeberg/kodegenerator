"""Persistence boundary for P3-14 task execution receipts."""
from __future__ import annotations

from sqlalchemy.orm import Session

from domain.task_execution import TaskExecutionReceipt, TaskExecutionStatus
from .models import TaskExecutionModel


class TaskExecutionRepository:
    """Organization-scoped durable execution receipt repository."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, execution_id: str, organization_id: str) -> TaskExecutionReceipt | None:
        row = (
            self.session.query(TaskExecutionModel)
            .filter(
                TaskExecutionModel.execution_id == execution_id,
                TaskExecutionModel.organization_id == organization_id,
            )
            .one_or_none()
        )
        if row is None:
            return None
        return self._to_domain(row)

    def add(self, receipt: TaskExecutionReceipt) -> None:
        self.session.add(
            TaskExecutionModel(
                execution_id=receipt.execution_id,
                organization_id=receipt.organization_id,
                actor_id=receipt.actor_id,
                task_type=receipt.task_type,
                capability_id=receipt.capability_id,
                payload=receipt.payload,
                status=receipt.status.value,
                result=receipt.result,
                error_code=receipt.error_code,
                error_message=receipt.error_message,
                resource_id=receipt.resource_id,
                resource_organization_id=receipt.resource_organization_id,
                created_at=receipt.created_at,
                updated_at=receipt.updated_at,
            )
        )

    def update(self, receipt: TaskExecutionReceipt) -> None:
        row = (
            self.session.query(TaskExecutionModel)
            .filter(
                TaskExecutionModel.execution_id == receipt.execution_id,
                TaskExecutionModel.organization_id == receipt.organization_id,
            )
            .one_or_none()
        )
        if row is None:
            raise KeyError(f"Execution not found: {receipt.execution_id}")
        row.status = receipt.status.value
        row.result = receipt.result
        row.error_code = receipt.error_code
        row.error_message = receipt.error_message
        row.updated_at = receipt.updated_at

    @staticmethod
    def _to_domain(row: TaskExecutionModel) -> TaskExecutionReceipt:
        return TaskExecutionReceipt(
            execution_id=row.execution_id,
            organization_id=row.organization_id,
            actor_id=row.actor_id,
            task_type=row.task_type,
            capability_id=row.capability_id,
            payload=row.payload,
            status=TaskExecutionStatus(row.status),
            result=row.result,
            error_code=row.error_code,
            error_message=row.error_message,
            resource_id=row.resource_id,
            resource_organization_id=row.resource_organization_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
