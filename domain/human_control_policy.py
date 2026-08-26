"""Human-in-the-loop autonomy policy for governed decisions."""
from __future__ import annotations

from dataclasses import dataclass

from .decision import DecisionCategory, RiskLevel


@dataclass(frozen=True)
class HumanControlPolicy:
    """Maps decision risk to the minimum required human control."""

    critical_requires_human: bool = True
    high_requires_human: bool = True
    medium_requires_unanimous_council: bool = True
    low_autonomous: bool = True

    def evaluate(self, *, risk_level: RiskLevel, category: DecisionCategory) -> str:
        """Return the required gate state for a proposed decision."""
        if risk_level in {RiskLevel.CRITICAL, RiskLevel.HIGH}:
            return "HUMAN_REQUIRED"
        if risk_level is RiskLevel.MEDIUM:
            return "COUNCIL_REQUIRED" if self.medium_requires_unanimous_council else "HUMAN_REQUIRED"
        if self.low_autonomous:
            return "AUTONOMOUS"
        return "HUMAN_REQUIRED"

    def requires_human(self, *, risk_level: RiskLevel, category: DecisionCategory) -> bool:
        """Apply category safety overrides before risk policy."""
        if category in {DecisionCategory.ARCHITECTURE, DecisionCategory.RELEASE}:
            return True
        return self.evaluate(risk_level=risk_level, category=category) == "HUMAN_REQUIRED"

    def gate_status(self, *, risk_level: RiskLevel, category: DecisionCategory) -> str:
        """Return the canonical Decision status implied by policy."""
        if self.requires_human(risk_level=risk_level, category=category):
            return "HUMAN_REQUIRED"
        return "PROPOSED"
