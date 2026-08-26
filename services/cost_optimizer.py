"""
Cost & Token Budget Optimizer

Provides full token/credit transparency and automatic cost optimization
for projects and capabilities.

Features:
- Usage recording with timestamps
- Project cost estimation by model price list
- Budget guarding (fail-closed)
- Model suggestion based on complexity and success rate
- Usage summary as JSON
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import TypedDict


class TaskPhase(str, Enum):
    """Phases of a task."""
    DOCUMENTATION = "documentation"
    TESTING = "testing"
    SIMPLE = "simple"
    COMPLEX = "complex"
    DOMAIN_MODELING = "domain_modeling"


class ModelTier(str, Enum):
    """Model pricing tiers."""
    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"


@dataclass
class ModelPrice:
    """Price information for a model."""
    model_id: str
    tier: ModelTier
    price_per_1k_input_tokens: float  # USD per 1000 input tokens
    price_per_1k_output_tokens: float  # USD per 1000 output tokens
    
    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Calculate cost for a given number of tokens."""
        return (
            (input_tokens / 1000) * self.price_per_1k_input_tokens +
            (output_tokens / 1000) * self.price_per_1k_output_tokens
        )


# Default model price list
DEFAULT_MODEL_PRICES: Dict[str, ModelPrice] = {
    "gpt-4": ModelPrice(
        model_id="gpt-4",
        tier=ModelTier.PREMIUM,
        price_per_1k_input_tokens=0.03,
        price_per_1k_output_tokens=0.06,
    ),
    "gpt-4-32k": ModelPrice(
        model_id="gpt-4-32k",
        tier=ModelTier.PREMIUM,
        price_per_1k_input_tokens=0.06,
        price_per_1k_output_tokens=0.12,
    ),
    "gpt-3.5-turbo": ModelPrice(
        model_id="gpt-3.5-turbo",
        tier=ModelTier.STANDARD,
        price_per_1k_input_tokens=0.0015,
        price_per_1k_output_tokens=0.002,
    ),
    "gpt-3.5-turbo-16k": ModelPrice(
        model_id="gpt-3.5-turbo-16k",
        tier=ModelTier.STANDARD,
        price_per_1k_input_tokens=0.003,
        price_per_1k_output_tokens=0.004,
    ),
    "claude-2": ModelPrice(
        model_id="claude-2",
        tier=ModelTier.PREMIUM,
        price_per_1k_input_tokens=0.011025,
        price_per_1k_output_tokens=0.032675,
    ),
    "claude-2:1": ModelPrice(
        model_id="claude-2:1",
        tier=ModelTier.PREMIUM,
        price_per_1k_input_tokens=0.008,
        price_per_1k_output_tokens=0.024,
    ),
    "claude-instant-1": ModelPrice(
        model_id="claude-instant-1",
        tier=ModelTier.ECONOMY,
        price_per_1k_input_tokens=0.00163,
        price_per_1k_output_tokens=0.00551,
    ),
    "mistral-7b": ModelPrice(
        model_id="mistral-7b",
        tier=ModelTier.ECONOMY,
        price_per_1k_input_tokens=0.00025,
        price_per_1k_output_tokens=0.00025,
    ),
    "llama-2-70b": ModelPrice(
        model_id="llama-2-70b",
        tier=ModelTier.STANDARD,
        price_per_1k_input_tokens=0.00079,
        price_per_1k_output_tokens=0.001,
    ),
}


@dataclass
class UsageRecord:
    """A single usage record."""
    project_id: str
    capability: str
    model: str
    tokens_in: int
    tokens_out: int
    timestamp: datetime
    phase: Optional[TaskPhase] = None
    complexity: float = 0.0  # 0.0 to 1.0, higher = more complex
    success: bool = True
    
    def cost(self, model_prices: Dict[str, ModelPrice]) -> float:
        """Calculate cost for this usage record."""
        price = model_prices.get(self.model)
        if price is None:
            return 0.0
        return price.cost(self.tokens_in, self.tokens_out)


@dataclass
class CostBreakdown:
    """Cost breakdown for a project."""
    project_id: str
    total_cost: float = 0.0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    by_capability: Dict[str, float] = field(default_factory=dict)
    by_phase: Dict[str, float] = field(default_factory=dict)
    by_model: Dict[str, float] = field(default_factory=dict)
    record_count: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class ModelSuggestion:
    """Model suggestion result."""
    capability: str
    suggested_model: str
    reason: str
    tier: ModelTier
    estimated_cost: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class UsageSummary:
    """Usage summary for a project."""
    project_id: str
    total_tokens: int = 0
    total_cost: float = 0.0
    by_capability: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    top_3_expensive_tasks: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(asdict(self), indent=2, default=str)


class CostOptimizer:
    """
    Cost & Token Budget Optimizer.
    
    Provides full token/credit transparency and automatic cost optimization
    for projects and capabilities.
    
    Usage:
        optimizer = CostOptimizer()
        
        # Record usage
        optimizer.record_usage(
            project_id="my-project",
            capability="code-generation",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
        )
        
        # Get project cost
        breakdown = optimizer.project_cost("my-project")
        print(f"Total cost: ${breakdown.total_cost}")
        
        # Check budget
        if optimizer.budget_guard("my-project", max_cost=100.0):
            # Proceed with task
            pass
        
        # Get model suggestion
        suggestion = optimizer.suggest_model("my-project", "code-generation")
        print(f"Suggested model: {suggestion.suggested_model}")
        
        # Get usage summary
        summary = optimizer.usage_summary("my-project")
        print(summary.to_json())
    """
    
    def __init__(
        self,
        *,
        model_prices: Optional[Dict[str, ModelPrice]] = None,
        default_model: str = "gpt-3.5-turbo",
        track_usage: bool = True,
    ):
        """
        Initialize the CostOptimizer.
        
        Args:
            model_prices: Custom model price list (overrides defaults)
            default_model: Default model to use when no suggestion is available
            track_usage: Whether to track usage history
        """
        self._model_prices = model_prices or DEFAULT_MODEL_PRICES.copy()
        self._default_model = default_model
        self._track_usage = track_usage
        
        # Usage storage
        self._usage: Dict[str, List[UsageRecord]] = {}  # project_id -> list of records
        self._usage_lock = threading.Lock()
        
        # Budget tracking
        self._budgets: Dict[str, float] = {}  # project_id -> current cost
        self._budget_lock = threading.Lock()
        
        # Model success tracking for suggestions
        self._model_success: Dict[str, Dict[str, Tuple[int, int]]] = {}  # project_id -> model -> (success, total)
        self._model_complexity: Dict[str, Dict[str, List[float]]] = {}  # project_id -> model -> list of complexity scores
        self._model_success_lock = threading.Lock()
    
    def record_usage(
        self,
        project_id: str,
        capability: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        phase: Optional[TaskPhase] = None,
        complexity: float = 0.0,
        success: bool = True,
    ) -> UsageRecord:
        """
        Record usage with timestamp.
        
        Args:
            project_id: The project ID
            capability: The capability being used
            model: The model being used
            tokens_in: Input tokens
            tokens_out: Output tokens
            phase: Optional task phase
            complexity: Complexity score (0.0 to 1.0)
            success: Whether the task was successful
            
        Returns:
            The created UsageRecord
        """
        record = UsageRecord(
            project_id=project_id,
            capability=capability,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            timestamp=datetime.now(),
            phase=phase,
            complexity=complexity,
            success=success,
        )
        
        if self._track_usage:
            with self._usage_lock:
                if project_id not in self._usage:
                    self._usage[project_id] = []
                self._usage[project_id].append(record)
            
            # Update budget tracking
            with self._budget_lock:
                cost = record.cost(self._model_prices)
                self._budgets[project_id] = self._budgets.get(project_id, 0.0) + cost
            
            # Update model success tracking
            with self._model_success_lock:
                if project_id not in self._model_success:
                    self._model_success[project_id] = {}
                if model not in self._model_success[project_id]:
                    self._model_success[project_id][model] = (0, 0)
                
                success_count, total_count = self._model_success[project_id][model]
                if success:
                    success_count += 1
                total_count += 1
                self._model_success[project_id][model] = (success_count, total_count)
                
                # Track complexity
                if project_id not in self._model_complexity:
                    self._model_complexity[project_id] = {}
                if model not in self._model_complexity[project_id]:
                    self._model_complexity[project_id][model] = []
                self._model_complexity[project_id][model].append(complexity)
        
        return record
    
    def project_cost(self, project_id: str) -> CostBreakdown:
        """
        Get estimated cost for a project, broken down by capability and phase.
        
        Args:
            project_id: The project ID
            
        Returns:
            CostBreakdown with total cost and breakdowns
        """
        with self._usage_lock:
            records = self._usage.get(project_id, [])
        
        breakdown = CostBreakdown(project_id=project_id)
        
        for record in records:
            cost = record.cost(self._model_prices)
            breakdown.total_cost += cost
            breakdown.total_tokens_in += record.tokens_in
            breakdown.total_tokens_out += record.tokens_out
            breakdown.record_count += 1
            
            # By capability
            if record.capability not in breakdown.by_capability:
                breakdown.by_capability[record.capability] = 0.0
            breakdown.by_capability[record.capability] += cost
            
            # By phase
            phase_str = record.phase.value if record.phase else "unknown"
            if phase_str not in breakdown.by_phase:
                breakdown.by_phase[phase_str] = 0.0
            breakdown.by_phase[phase_str] += cost
            
            # By model
            if record.model not in breakdown.by_model:
                breakdown.by_model[record.model] = 0.0
            breakdown.by_model[record.model] += cost
        
        return breakdown
    
    def budget_guard(
        self,
        project_id: str,
        max_cost: float,
    ) -> bool:
        """
        Block new tasks if project budget is exceeded (fail-closed).
        
        Args:
            project_id: The project ID
            max_cost: Maximum allowed cost
            
        Returns:
            True if under budget, False if budget exceeded
        """
        with self._budget_lock:
            current_cost = self._budgets.get(project_id, 0.0)
            return current_cost <= max_cost
    
    def get_current_cost(self, project_id: str) -> float:
        """
        Get the current cost for a project.
        
        Args:
            project_id: The project ID
            
        Returns:
            Current cost in USD
        """
        with self._budget_lock:
            return self._budgets.get(project_id, 0.0)
    
    def suggest_model(
        self,
        project_id: str,
        capability: str,
        complexity: Optional[float] = None,
    ) -> ModelSuggestion:
        """
        Suggest a model based on complexity and success rate.
        
        For simple tasks (docs, tests), suggests cheaper models.
        For complex tasks (domain modeling), suggests premium models.
        
        Args:
            project_id: The project ID
            capability: The capability
            complexity: Optional complexity override (0.0 to 1.0)
            
        Returns:
            ModelSuggestion with suggested model and reasoning
        """
        # Determine complexity
        if complexity is None:
            # Use historical complexity for this project
            with self._model_success_lock:
                if project_id in self._model_complexity:
                    all_complexities = []
                    for model_complexities in self._model_complexity[project_id].values():
                        all_complexities.extend(model_complexities)
                    if all_complexities:
                        complexity = sum(all_complexities) / len(all_complexities)
                    else:
                        complexity = 0.5
                else:
                    complexity = 0.5
        
        # Determine phase from capability
        if capability in ["documentation", "docs", "commenting"]:
            phase = TaskPhase.DOCUMENTATION
        elif capability in ["testing", "test-generation", "validation"]:
            phase = TaskPhase.TESTING
        elif capability in ["domain-modeling", "architecture", "design"]:
            phase = TaskPhase.DOMAIN_MODELING
        else:
            phase = TaskPhase.COMPLEX if complexity > 0.7 else TaskPhase.SIMPLE
        
        # Get available models sorted by tier
        economy_models = [
            m for m, p in self._model_prices.items() 
            if p.tier == ModelTier.ECONOMY
        ]
        standard_models = [
            m for m, p in self._model_prices.items() 
            if p.tier == ModelTier.STANDARD
        ]
        premium_models = [
            m for m, p in self._model_prices.items() 
            if p.tier == ModelTier.PREMIUM
        ]
        
        # Choose tier based on complexity and phase
        if phase in [TaskPhase.DOCUMENTATION, TaskPhase.TESTING] or complexity < 0.3:
            tier = ModelTier.ECONOMY
            candidates = economy_models
            reason = f"Low complexity ({complexity:.2f}) task for {capability}"
        elif phase == TaskPhase.DOMAIN_MODELING or complexity > 0.7:
            tier = ModelTier.PREMIUM
            candidates = premium_models
            reason = f"High complexity ({complexity:.2f}) task for {capability}"
        else:
            tier = ModelTier.STANDARD
            candidates = standard_models
            reason = f"Medium complexity ({complexity:.2f}) task for {capability}"
        
        # If no candidates in the chosen tier, use the next available
        if not candidates:
            if tier == ModelTier.ECONOMY:
                candidates = standard_models
                tier = ModelTier.STANDARD
                reason += ", economy models not available, using standard"
            elif tier == ModelTier.STANDARD:
                candidates = premium_models
                tier = ModelTier.PREMIUM
                reason += ", standard models not available, using premium"
            else:
                candidates = economy_models or standard_models
                tier = ModelTier.ECONOMY if economy_models else ModelTier.STANDARD
                reason += ", premium models not available, using available tier"
        
        # Select the cheapest model in the tier
        suggested_model = min(candidates, key=lambda m: self._model_prices[m].cost(1000, 0)) if candidates else self._default_model
        
        # Calculate estimated cost (for 1000 input + 500 output tokens as example)
        price = self._model_prices.get(suggested_model)
        estimated_cost = price.cost(1000, 500) if price else 0.0
        
        return ModelSuggestion(
            capability=capability,
            suggested_model=suggested_model,
            reason=reason,
            tier=tier,
            estimated_cost=estimated_cost,
        )
    
    def usage_summary(self, project_id: str) -> UsageSummary:
        """
        Get usage summary for a project as JSON-serializable dict.
        
        Args:
            project_id: The project ID
            
        Returns:
            UsageSummary with aggregated data
        """
        with self._usage_lock:
            records = self._usage.get(project_id, [])
        
        summary = UsageSummary(project_id=project_id)
        
        # Aggregate by capability
        capability_data: Dict[str, Dict[str, Any]] = {}
        for record in records:
            cost = record.cost(self._model_prices)
            summary.total_tokens += record.tokens_in + record.tokens_out
            summary.total_cost += cost
            
            # By capability
            if record.capability not in capability_data:
                capability_data[record.capability] = {
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "cost": 0.0,
                    "record_count": 0,
                }
            cap_data = capability_data[record.capability]
            cap_data["tokens_in"] += record.tokens_in
            cap_data["tokens_out"] += record.tokens_out
            cap_data["cost"] += cost
            cap_data["record_count"] += 1
        
        summary.by_capability = capability_data
        
        # Find top 3 most expensive tasks
        sorted_records = sorted(records, key=lambda r: r.cost(self._model_prices), reverse=True)
        summary.top_3_expensive_tasks = [
            {
                "capability": r.capability,
                "model": r.model,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "cost": r.cost(self._model_prices),
                "timestamp": r.timestamp.isoformat(),
            }
            for r in sorted_records[:3]
        ]
        
        return summary
    
    def get_model_prices(self) -> Dict[str, ModelPrice]:
        """Get the current model price list."""
        return self._model_prices.copy()
    
    def set_model_price(self, model_id: str, price: ModelPrice) -> None:
        """Set or update a model price."""
        self._model_prices[model_id] = price
    
    def reset(self, project_id: Optional[str] = None) -> None:
        """Reset usage and budget tracking."""
        if project_id:
            with self._usage_lock:
                if project_id in self._usage:
                    del self._usage[project_id]
            with self._budget_lock:
                if project_id in self._budgets:
                    del self._budgets[project_id]
            with self._model_success_lock:
                if project_id in self._model_success:
                    del self._model_success[project_id]
                if project_id in self._model_complexity:
                    del self._model_complexity[project_id]
        else:
            with self._usage_lock:
                self._usage.clear()
            with self._budget_lock:
                self._budgets.clear()
            with self._model_success_lock:
                self._model_success.clear()
                self._model_complexity.clear()


# Global optimizer instance
_optimizer: Optional[CostOptimizer] = None


def get_cost_optimizer(**kwargs) -> CostOptimizer:
    """Get or create the global CostOptimizer instance."""
    global _optimizer
    if _optimizer is None:
        _optimizer = CostOptimizer(**kwargs)
    return _optimizer


def record_usage(
    project_id: str,
    capability: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    **kwargs,
) -> UsageRecord:
    """Convenience function to record usage."""
    optimizer = get_cost_optimizer()
    return optimizer.record_usage(
        project_id=project_id,
        capability=capability,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        **kwargs,
    )


def project_cost(project_id: str) -> CostBreakdown:
    """Convenience function to get project cost."""
    optimizer = get_cost_optimizer()
    return optimizer.project_cost(project_id)


def budget_guard(project_id: str, max_cost: float) -> bool:
    """Convenience function to check budget."""
    optimizer = get_cost_optimizer()
    return optimizer.budget_guard(project_id, max_cost)


def suggest_model(project_id: str, capability: str, **kwargs) -> ModelSuggestion:
    """Convenience function to suggest model."""
    optimizer = get_cost_optimizer()
    return optimizer.suggest_model(project_id, capability, **kwargs)


def usage_summary(project_id: str) -> UsageSummary:
    """Convenience function to get usage summary."""
    optimizer = get_cost_optimizer()
    return optimizer.usage_summary(project_id)
