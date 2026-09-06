"""Operator-only swarm operations metrics & health REST surface.

* GET /api/v1/swarm/ops/snapshot  — full JSON state snapshot
* GET /api/v1/swarm/ops/metrics   — Prometheus text exposition
* GET /api/v1/swarm/ops/health    — per-component health

These values are process/global operational data and are therefore not a
tenant-facing surface. Access is limited to the configured platform operator
and additionally requires an administrator membership for that operator.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Response, status

from api.auth import User, get_current_active_user
from api.dependencies import get_dor
from infrastructure.persistence.models import OrganizationMembershipModel
from runtime.core import DORRuntime
from services.operations_metrics import OperationsMetrics, default_operations_metrics


def _require_platform_operator(
    current_user: User = Depends(get_current_active_user),
    dor: DORRuntime = Depends(get_dor),
) -> User:
    operator_username = (
        os.getenv("DOR_OPERATOR_USERNAME")
        or os.getenv("DOR_ADMIN_USERNAME")
        or "admin"
    ).strip()
    operator_organization = (
        os.getenv("DOR_OPERATOR_ORGANIZATION_ID")
        or os.getenv("DOR_ADMIN_ORGANIZATION_ID")
        or ""
    ).strip()
    organization_id = current_user.organization_id
    if (
        current_user.username != operator_username
        or not organization_id
        or (operator_organization and organization_id != operator_organization)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "platform_operator_required"},
        )

    with dor.database.session() as session:
        membership = session.get(
            OrganizationMembershipModel,
            (current_user.username, organization_id),
        )
    if membership is None or not membership.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "platform_operator_required"},
        )
    return current_user


router = APIRouter(
    prefix="/api/v1/swarm/ops",
    tags=["swarm-ops"],
    dependencies=[Depends(_require_platform_operator)],
)

_metrics: OperationsMetrics = default_operations_metrics


def get_metrics() -> OperationsMetrics:
    return _metrics


def set_metrics(metrics: OperationsMetrics) -> None:
    """Test/DI hook."""
    global _metrics
    _metrics = metrics


@router.get("/snapshot")
async def ops_snapshot() -> dict:
    """Full swarm operations state snapshot."""
    return get_metrics().snapshot()


@router.get("/metrics")
async def ops_prometheus_metrics() -> Response:
    """Prometheus-compatible metrics exposition."""
    body = get_metrics().prometheus_metrics()
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.get("/health")
async def ops_health() -> dict:
    """Simple health document with per-component status."""
    return get_metrics().health()
