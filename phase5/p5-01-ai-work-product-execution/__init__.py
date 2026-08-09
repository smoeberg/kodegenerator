"""P5-01 AI work-product execution boundary.

P5-01 executes an already-defined P5-00 contract. It never verifies the
result and never creates an authoritative PASSED/FAILED decision.
"""

from .execution import ExecutionContext, ExecutionEngine, ExecutionError, ExecutionResult

__all__ = ["ExecutionContext", "ExecutionEngine", "ExecutionError", "ExecutionResult"]
