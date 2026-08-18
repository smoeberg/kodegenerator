"""Phase 4 AI-4 Execution Engine public contract."""

from .adapters import AdapterResult, ExecutionAdapter, StaticExecutionAdapter
from .engine import ExecutionEngine, ExecutionError, ExecutionRejected
from .ledger import (
    ClaimResult,
    ExecutionLedger,
    InProcessLedger,
    LedgerRecord,
    PendingClaimOutcome,
    ReplayPolicy,
)
from .models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    GovernedDispatch,
    execution_id_for,
)

__all__ = [
    "AdapterResult",
    "ExecutionAdapter",
    "StaticExecutionAdapter",
    "ExecutionEngine",
    "ExecutionError",
    "ExecutionRejected",
    "ClaimResult",
    "ExecutionLedger",
    "InProcessLedger",
    "LedgerRecord",
    "PendingClaimOutcome",
    "ReplayPolicy",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "GovernedDispatch",
    "execution_id_for",
]

__version__ = "4.0.0"
