"""Swarm operations metrics & health REST surface.

* GET /api/v1/swarm/ops/snapshot  — full JSON state snapshot
* GET /api/v1/swarm/ops/metrics   — Prometheus text exposition
* GET /api/v1/swarm/ops/health    — per-component health

Auth is applied at router include time (same as other /api/v1/swarm/* routes).
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from services.operations_metrics import OperationsMetrics, default_operations_metrics

router = APIRouter(prefix="/api/v1/swarm/ops", tags=["swarm-ops"])

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
