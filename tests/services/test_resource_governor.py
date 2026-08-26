import pytest
from services.resource_governor import ResourceGovernor

def test_rate_limiting_with_burst_tolerance():
    gov = ResourceGovernor(default_capacity=5.0, default_refill_rate=0.0)
    for _ in range(5):
        assert gov.acquire_budget("security", 1.0) is True
    assert gov.acquire_budget("security", 1.0) is False
    assert gov.total_consumed("security") == 5.0

def test_file_concurrency_locking():
    gov = ResourceGovernor()
    file_path = "services/core.py"
    
    assert gov.acquire_file_lock(file_path) is True
    assert gov.acquire_file_lock(file_path) is False
    
    gov.release_file_lock(file_path)
    assert gov.acquire_file_lock(file_path) is True

def test_capability_isolated_budgets():
    gov = ResourceGovernor(default_capacity=2.0, default_refill_rate=0.0)
    assert gov.acquire_budget("api", 2.0) is True
    assert gov.acquire_budget("api", 1.0) is False
    assert gov.acquire_budget("docs", 2.0) is True
