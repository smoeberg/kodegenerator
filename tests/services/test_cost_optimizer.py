"""
Tests for Cost Optimizer service.

Tests cover:
- Correct cost calculation with different model prices
- Budget guard blocking after exceedance and allowing under budget
- Model suggestion choosing economy tier for docs and premium for domain modeling
- Usage summary aggregation across capabilities
"""

from __future__ import annotations

import json
import pytest

from services.cost_optimizer import (
    CostOptimizer,
    ModelPrice,
    ModelTier,
    UsageRecord,
    CostBreakdown,
    ModelSuggestion,
    UsageSummary,
    TaskPhase,
    get_cost_optimizer,
    record_usage,
    project_cost,
    budget_guard,
    suggest_model,
    usage_summary,
)


class TestModelPrice:
    """Tests for ModelPrice."""
    
    def test_cost_calculation(self):
        """Test cost calculation for a model."""
        price = ModelPrice(
            model_id="test",
            tier=ModelTier.STANDARD,
            price_per_1k_input_tokens=0.01,
            price_per_1k_output_tokens=0.02,
        )
        
        # 1000 input tokens, 500 output tokens
        # Input: 1000/1000 * 0.01 = 0.01
        # Output: 500/1000 * 0.02 = 0.01
        # Total: 0.02
        cost = price.cost(1000, 500)
        assert cost == pytest.approx(0.02)
    
    def test_cost_zero_tokens(self):
        """Test cost with zero tokens."""
        price = ModelPrice(
            model_id="test",
            tier=ModelTier.STANDARD,
            price_per_1k_input_tokens=0.01,
            price_per_1k_output_tokens=0.02,
        )
        
        cost = price.cost(0, 0)
        assert cost == 0.0
    
    def test_cost_large_tokens(self):
        """Test cost with large token counts."""
        price = ModelPrice(
            model_id="test",
            tier=ModelTier.PREMIUM,
            price_per_1k_input_tokens=0.03,
            price_per_1k_output_tokens=0.06,
        )
        
        # 100k input, 50k output
        cost = price.cost(100000, 50000)
        # Input: 100000/1000 * 0.03 = 3.0
        # Output: 50000/1000 * 0.06 = 3.0
        # Total: 6.0
        assert cost == pytest.approx(6.0)


class TestUsageRecord:
    """Tests for UsageRecord."""
    
    def test_usage_record_creation(self):
        """Test creating a usage record."""
        from datetime import datetime
        record = UsageRecord(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
            timestamp=datetime.now(),
        )
        
        assert record.project_id == "test-project"
        assert record.capability == "code-generation"
        assert record.model == "gpt-4"
        assert record.tokens_in == 1000
        assert record.tokens_out == 500
    
    def test_usage_record_cost(self):
        """Test cost calculation for usage record."""
        from datetime import datetime
        model_prices = {
            "gpt-4": ModelPrice(
                model_id="gpt-4",
                tier=ModelTier.PREMIUM,
                price_per_1k_input_tokens=0.03,
                price_per_1k_output_tokens=0.06,
            )
        }
        
        record = UsageRecord(
            project_id="test",
            capability="test",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
            timestamp=datetime.now(),
        )
        
        cost = record.cost(model_prices)
        assert cost == pytest.approx(0.06)  # (1000/1000 * 0.03) + (500/1000 * 0.06) = 0.03 + 0.03


class TestCostBreakdown:
    """Tests for CostBreakdown."""
    
    def test_cost_breakdown_creation(self):
        """Test creating a cost breakdown."""
        breakdown = CostBreakdown(project_id="test")
        
        assert breakdown.project_id == "test"
        assert breakdown.total_cost == 0.0
        assert breakdown.total_tokens_in == 0
        assert breakdown.total_tokens_out == 0
    
    def test_cost_breakdown_to_dict(self):
        """Test converting cost breakdown to dict."""
        breakdown = CostBreakdown(
            project_id="test",
            total_cost=100.0,
            total_tokens_in=10000,
            total_tokens_out=5000,
            by_capability={"code": 50.0, "docs": 50.0},
        )
        
        result = breakdown.to_dict()
        assert result["project_id"] == "test"
        assert result["total_cost"] == 100.0
        assert result["by_capability"]["code"] == 50.0


class TestCostOptimizer:
    """Tests for CostOptimizer."""
    
    def test_record_usage(self):
        """Test recording usage."""
        optimizer = CostOptimizer()
        
        record = optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        assert record.project_id == "test-project"
        assert record.tokens_in == 1000
        assert record.tokens_out == 500
    
    def test_record_usage_with_phase(self):
        """Test recording usage with phase."""
        optimizer = CostOptimizer()
        
        record = optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="gpt-3.5-turbo",
            tokens_in=500,
            tokens_out=250,
            phase=TaskPhase.DOCUMENTATION,
            complexity=0.2,
            success=True,
        )
        
        assert record.phase == TaskPhase.DOCUMENTATION
        assert record.complexity == 0.2
        assert record.success is True
    
    def test_project_cost_single_record(self):
        """Test project cost with a single record."""
        optimizer = CostOptimizer()
        
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        breakdown = optimizer.project_cost("test-project")
        
        assert breakdown.project_id == "test-project"
        assert breakdown.record_count == 1
        assert breakdown.total_tokens_in == 1000
        assert breakdown.total_tokens_out == 500
        # gpt-4: 0.03 per 1k input, 0.06 per 1k output
        # 1000 input: 0.03, 500 output: 0.03, total: 0.06
        assert breakdown.total_cost == pytest.approx(0.06)
    
    def test_project_cost_multiple_records(self):
        """Test project cost with multiple records."""
        optimizer = CostOptimizer()
        
        # Record 1: gpt-4, 1000 in, 500 out
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        # Record 2: gpt-3.5-turbo, 500 in, 250 out
        optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="gpt-3.5-turbo",
            tokens_in=500,
            tokens_out=250,
        )
        
        breakdown = optimizer.project_cost("test-project")
        
        assert breakdown.record_count == 2
        assert breakdown.total_tokens_in == 1500
        assert breakdown.total_tokens_out == 750
        # gpt-4: 0.03 * 1 + 0.06 * 0.5 = 0.03 + 0.03 = 0.06
        # gpt-3.5-turbo: 0.0015 * 0.5 + 0.002 * 0.25 = 0.00075 + 0.0005 = 0.00125
        # Total: 0.06125
        assert breakdown.total_cost == pytest.approx(0.06125)
    
    def test_project_cost_by_capability(self):
        """Test project cost breakdown by capability."""
        optimizer = CostOptimizer()
        
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="gpt-4",
            tokens_in=500,
            tokens_out=250,
        )
        
        breakdown = optimizer.project_cost("test-project")
        
        assert "code-generation" in breakdown.by_capability
        assert "documentation" in breakdown.by_capability
        # code-generation: 0.06
        # documentation: 0.03 + 0.015 = 0.045
        assert breakdown.by_capability["code-generation"] == pytest.approx(0.06)
        assert breakdown.by_capability["documentation"] == pytest.approx(0.03)  # 500/1000 * 0.03 + 250/1000 * 0.06
    
    def test_project_cost_by_phase(self):
        """Test project cost breakdown by phase."""
        optimizer = CostOptimizer()
        
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
            phase=TaskPhase.COMPLEX,
        )
        
        optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="gpt-4",
            tokens_in=500,
            tokens_out=250,
            phase=TaskPhase.DOCUMENTATION,
        )
        
        breakdown = optimizer.project_cost("test-project")
        
        assert "complex" in breakdown.by_phase
        assert "documentation" in breakdown.by_phase
    
    def test_budget_guard_under_budget(self):
        """Test budget guard allows under budget."""
        optimizer = CostOptimizer()
        
        # No usage yet
        result = optimizer.budget_guard("test-project", max_cost=100.0)
        assert result is True
        
        # Add some usage (cost ~0.06)
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        # Still under budget
        result = optimizer.budget_guard("test-project", max_cost=100.0)
        assert result is True
    
    def test_budget_guard_over_budget(self):
        """Test budget guard blocks over budget."""
        optimizer = CostOptimizer()
        
        # Add usage that exceeds budget
        # Each call to gpt-4 with 1000 in, 500 out costs ~0.06
        # Need more than 1.00 to exceed budget of 1.00
        for _ in range(20):
            optimizer.record_usage(
                project_id="test-project",
                capability="code-generation",
                model="gpt-4",
                tokens_in=1000,
                tokens_out=500,
            )
        
        # Should be over budget
        result = optimizer.budget_guard("test-project", max_cost=1.0)
        assert result is False
    
    def test_budget_guard_multiple_projects(self):
        """Test budget guard with multiple projects."""
        optimizer = CostOptimizer()
        
        # Add usage to project 1
        optimizer.record_usage(
            project_id="project-1",
            capability="code-generation",
            model="gpt-4",
            tokens_in=10000,
            tokens_out=5000,
        )
        
        # Add usage to project 2
        optimizer.record_usage(
            project_id="project-2",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        # Project 1 should be over budget (cost ~0.60)
        result = optimizer.budget_guard("project-1", max_cost=0.5)
        assert result is False
        
        # Project 2 should be under budget (cost ~0.06)
        result = optimizer.budget_guard("project-2", max_cost=0.5)
        assert result is True
    
    def test_suggest_model_for_documentation(self):
        """Test model suggestion for documentation tasks."""
        optimizer = CostOptimizer()
        
        # For documentation, should suggest economy tier
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="documentation",
        )
        
        assert suggestion.capability == "documentation"
        # Should suggest an economy model
        assert suggestion.tier == ModelTier.ECONOMY
        assert "claude-instant" in suggestion.suggested_model or "mistral" in suggestion.suggested_model or "economy" in suggestion.reason.lower()
    
    def test_suggest_model_for_domain_modeling(self):
        """Test model suggestion for domain modeling tasks."""
        optimizer = CostOptimizer()
        
        # For domain modeling, should suggest premium tier
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="domain-modeling",
        )
        
        assert suggestion.capability == "domain-modeling"
        assert suggestion.tier == ModelTier.PREMIUM
        assert "gpt-4" in suggestion.suggested_model or "claude" in suggestion.suggested_model or "premium" in suggestion.reason.lower()
    
    def test_suggest_model_with_complexity(self):
        """Test model suggestion with explicit complexity."""
        optimizer = CostOptimizer()
        
        # Low complexity (0.1) should suggest economy
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="code-generation",
            complexity=0.1,
        )
        
        assert suggestion.tier == ModelTier.ECONOMY
    
        # High complexity (0.9) should suggest premium
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="code-generation",
            complexity=0.9,
        )
        
        assert suggestion.tier == ModelTier.PREMIUM
    
    def test_suggest_model_to_dict(self):
        """Test model suggestion to dict."""
        optimizer = CostOptimizer()
        
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="code-generation",
        )
        
        result = suggestion.to_dict()
        assert "capability" in result
        assert "suggested_model" in result
        assert "tier" in result
    
    def test_usage_summary(self):
        """Test usage summary."""
        optimizer = CostOptimizer()
        
        # Add some usage
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="gpt-3.5-turbo",
            tokens_in=500,
            tokens_out=250,
        )
        
        summary = optimizer.usage_summary("test-project")
        
        assert summary.project_id == "test-project"
        assert summary.total_tokens == 2250  # 1000 + 500 + 500 + 250
        assert "code-generation" in summary.by_capability
        assert "documentation" in summary.by_capability
        assert len(summary.top_3_expensive_tasks) <= 3
    
    def test_usage_summary_top_3(self):
        """Test usage summary top 3 expensive tasks."""
        optimizer = CostOptimizer()
        
        # Add multiple records with different costs
        for i in range(5):
            optimizer.record_usage(
                project_id="test-project",
                capability=f"task-{i}",
                model="gpt-4",
                tokens_in=1000 * (i + 1),
                tokens_out=500 * (i + 1),
            )
        
        summary = optimizer.usage_summary("test-project")
        
        # Should have top 3 most expensive
        assert len(summary.top_3_expensive_tasks) == 3
        # Most expensive should be task-4 (5000 in, 2500 out)
        assert summary.top_3_expensive_tasks[0]["capability"] == "task-4"
    
    def test_usage_summary_json(self):
        """Test usage summary JSON serialization."""
        optimizer = CostOptimizer()
        
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        summary = optimizer.usage_summary("test-project")
        json_str = summary.to_json()
        
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["project_id"] == "test-project"
        assert "by_capability" in parsed
    
    def test_get_current_cost(self):
        """Test getting current cost."""
        optimizer = CostOptimizer()
        
        # No usage
        assert optimizer.get_current_cost("test-project") == 0.0
        
        # Add usage
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        cost = optimizer.get_current_cost("test-project")
        assert cost == pytest.approx(0.06)
    
    def test_reset_project(self):
        """Test resetting a single project."""
        optimizer = CostOptimizer()
        
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        # Verify usage exists
        breakdown = optimizer.project_cost("test-project")
        assert breakdown.record_count == 1
        
        # Reset
        optimizer.reset("test-project")
        
        # Verify usage is cleared
        breakdown = optimizer.project_cost("test-project")
        assert breakdown.record_count == 0
    
    def test_reset_all(self):
        """Test resetting all projects."""
        optimizer = CostOptimizer()
        
        optimizer.record_usage(
            project_id="project-1",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        optimizer.record_usage(
            project_id="project-2",
            capability="documentation",
            model="gpt-4",
            tokens_in=500,
            tokens_out=250,
        )
        
        # Reset all
        optimizer.reset()
        
        # Verify all usage is cleared
        breakdown1 = optimizer.project_cost("project-1")
        breakdown2 = optimizer.project_cost("project-2")
        assert breakdown1.record_count == 0
        assert breakdown2.record_count == 0
    
    def test_custom_model_prices(self):
        """Test with custom model prices."""
        custom_prices = {
            "custom-model": ModelPrice(
                model_id="custom-model",
                tier=ModelTier.STANDARD,
                price_per_1k_input_tokens=0.05,
                price_per_1k_output_tokens=0.10,
            )
        }
        
        optimizer = CostOptimizer(model_prices=custom_prices)
        
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="custom-model",
            tokens_in=1000,
            tokens_out=500,
        )
        
        breakdown = optimizer.project_cost("test-project")
        # 1000/1000 * 0.05 + 500/1000 * 0.10 = 0.05 + 0.05 = 0.10
        assert breakdown.total_cost == pytest.approx(0.10)


class TestGlobalOptimizer:
    """Tests for global optimizer instance."""
    
    def test_get_cost_optimizer(self):
        """Test getting global optimizer instance."""
        # Reset global
        import services.cost_optimizer as co
        co._optimizer = None
        
        optimizer = get_cost_optimizer()
        assert optimizer is not None
        
        # Should return same instance
        optimizer2 = get_cost_optimizer()
        assert optimizer is optimizer2
    
    def test_convenience_functions(self):
        """Test convenience functions."""
        # Reset global
        import services.cost_optimizer as co
        co._optimizer = None
        
        record = record_usage(
            project_id="test",
            capability="test",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        assert record.project_id == "test"
        
        breakdown = project_cost("test")
        assert breakdown.record_count == 1
        
        result = budget_guard("test", max_cost=100.0)
        assert result is True
        
        suggestion = suggest_model("test", "test")
        assert suggestion.capability == "test"
        
        summary = usage_summary("test")
        assert summary.project_id == "test"


class TestCostCalculationWithDifferentPrices:
    """Tests for cost calculation with different model prices."""
    
    def test_two_models_different_prices(self):
        """Test cost calculation with two different model prices."""
        optimizer = CostOptimizer()
        
        # Use two different models with different prices
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="claude-instant-1",
            tokens_in=1000,
            tokens_out=500,
        )
        
        breakdown = optimizer.project_cost("test-project")
        
        # gpt-4: 0.03 + 0.03 = 0.06
        # claude-instant-1: 0.00163 + 0.002755 = ~0.004385
        # Total: ~0.064385
        expected_cost = 0.06 + (0.00163 + 0.00551 / 2)
        assert breakdown.total_cost == pytest.approx(expected_cost, rel=0.01)
        
        # Verify by_model breakdown
        assert "gpt-4" in breakdown.by_model
        assert "claude-instant-1" in breakdown.by_model


class TestBudgetGuardBlocking:
    """Tests for budget guard blocking behavior."""
    
    def test_budget_guard_fail_closed(self):
        """Test that budget guard is fail-closed (blocks when over budget)."""
        optimizer = CostOptimizer()
        
        # Add usage that exceeds budget
        for _ in range(50):
            optimizer.record_usage(
                project_id="test-project",
                capability="code-generation",
                model="gpt-4",
                tokens_in=1000,
                tokens_out=500,
            )
        
        # Should be well over budget
        result = optimizer.budget_guard("test-project", max_cost=1.0)
        assert result is False
    
    def test_budget_guard_allows_under_budget(self):
        """Test that budget guard allows when under budget."""
        optimizer = CostOptimizer()
        
        # Add minimal usage
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-3.5-turbo",
            tokens_in=100,
            tokens_out=50,
        )
        
        # Should be under budget
        result = optimizer.budget_guard("test-project", max_cost=100.0)
        assert result is True


class TestModelSuggestionComplexity:
    """Tests for model suggestion based on complexity."""
    
    def test_suggest_economy_for_docs(self):
        """Test that economy models are suggested for documentation."""
        optimizer = CostOptimizer()
        
        # Record some successful documentation tasks with low complexity
        for _ in range(5):
            optimizer.record_usage(
                project_id="test-project",
                capability="documentation",
                model="gpt-4",
                tokens_in=1000,
                tokens_out=500,
                phase=TaskPhase.DOCUMENTATION,
                complexity=0.1,
                success=True,
            )
        
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="documentation",
        )
        
        # Should suggest economy tier for documentation
        assert suggestion.tier == ModelTier.ECONOMY
    
    def test_suggest_premium_for_domain(self):
        """Test that premium models are suggested for domain modeling."""
        optimizer = CostOptimizer()
        
        # Record some complex domain modeling tasks
        for _ in range(5):
            optimizer.record_usage(
                project_id="test-project",
                capability="domain-modeling",
                model="gpt-3.5-turbo",
                tokens_in=10000,
                tokens_out=5000,
                phase=TaskPhase.DOMAIN_MODELING,
                complexity=0.9,
                success=True,
            )
        
        suggestion = optimizer.suggest_model(
            project_id="test-project",
            capability="domain-modeling",
        )
        
        # Should suggest premium tier for domain modeling
        assert suggestion.tier == ModelTier.PREMIUM


class TestUsageSummaryAggregation:
    """Tests for usage summary aggregation across capabilities."""
    
    def test_summary_aggregates_correctly(self):
        """Test that usage summary aggregates correctly across capabilities."""
        optimizer = CostOptimizer()
        
        # Add usage for multiple capabilities
        optimizer.record_usage(
            project_id="test-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=10000,
            tokens_out=5000,
        )
        
        optimizer.record_usage(
            project_id="test-project",
            capability="documentation",
            model="gpt-3.5-turbo",
            tokens_in=5000,
            tokens_out=2500,
        )
        
        optimizer.record_usage(
            project_id="test-project",
            capability="testing",
            model="gpt-3.5-turbo",
            tokens_in=2000,
            tokens_out=1000,
        )
        
        summary = optimizer.usage_summary("test-project")
        
        # Check total tokens
        assert summary.total_tokens == 25500  # 10000+5000+5000+2500+2000+1000
        
        # Check by_capability
        assert "code-generation" in summary.by_capability
        assert "documentation" in summary.by_capability
        assert "testing" in summary.by_capability
        
        # Check top 3 (should be all 3 since we only have 3)
        assert len(summary.top_3_expensive_tasks) == 3
        # Most expensive should be code-generation with gpt-4
        assert summary.top_3_expensive_tasks[0]["capability"] == "code-generation"
