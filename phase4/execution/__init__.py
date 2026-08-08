"""Phase 4 AI-4 Execution Engine public contract."""

from .adapters import AdapterResult, ExecutionAdapter, StaticExecutionAdapter
from .engine import ExecutionEngine, ExecutionError, ExecutionRejected
from .models import ExecutionRequest, ExecutionResult, ExecutionStatus, execution_id_for

__all__ = [
    "AdapterResult",
    "ExecutionAdapter",
    "StaticExecutionAdapter",
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionRejected",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "execution_id_for",
]

__version__ = "4.0.0"
