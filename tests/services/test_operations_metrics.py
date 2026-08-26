"""Tests for services.operations_metrics.OperationsMetrics."""

from __future__ import annotations

from services.operations_metrics import OperationsMetrics


REQUIRED_SNAPSHOT_KEYS = {
    "captured_at",
    "status",
    "queue",
    "workers",
    "dlq",
    "circuit_breakers",
    "performance",
    "cost",
    "components",
}


def test_snapshot_contains_all_sections():
    metrics = OperationsMetrics()
    snap = metrics.snapshot()
    assert REQUIRED_SNAPSHOT_KEYS.issubset(snap.keys())
    assert "depth_by_status" in snap["queue"]
    assert "depth_by_capability" in snap["queue"]
    assert "active" in snap["workers"]
    assert "total" in snap["workers"]
    assert "size" in snap["dlq"]
    assert isinstance(snap["circuit_breakers"], dict)
    assert isinstance(snap["performance"], dict)
    assert isinstance(snap["cost"], dict)
    assert isinstance(snap["components"], dict)


def test_snapshot_status_degraded_when_component_degraded():
    metrics = OperationsMetrics()
    metrics.bind_component_health({"queue": "ok", "dlq": "degraded"})
    assert metrics.snapshot()["status"] == "degraded"


def test_snapshot_status_down_when_component_down():
    metrics = OperationsMetrics()
    metrics.bind_component_health({"queue": "down", "workers": "ok"})
    assert metrics.snapshot()["status"] == "down"


def test_prometheus_format_core_lines():
    metrics = OperationsMetrics()
    metrics.bind_queue_depth({"pending": 12, "running": 3})
    metrics.bind_workers(active=5, total=8)
    metrics.bind_dlq_size(2)
    text = metrics.prometheus_metrics()

    assert 'swarm_queue_depth{status="pending"} 12' in text
    assert 'swarm_queue_depth{status="running"} 3' in text
    assert "swarm_workers_active 5" in text
    assert "swarm_workers_total 8" in text
    assert "swarm_dlq_size 2" in text
    assert "swarm_circuit_breaker{" in text
    assert "# TYPE swarm_queue_depth gauge" in text
    assert text.endswith("\n")


def test_prometheus_capability_lines():
    metrics = OperationsMetrics()
    metrics.bind_queue_by_capability({"code": 8, "test": 5})
    text = metrics.prometheus_metrics()
    assert 'swarm_queue_depth_by_capability{capability="code"} 8' in text
    assert 'swarm_queue_depth_by_capability{capability="test"} 5' in text


def test_health_subset():
    metrics = OperationsMetrics()
    h = metrics.health()
    assert set(h.keys()) >= {"status", "components", "captured_at"}
    assert isinstance(h["components"], dict)
