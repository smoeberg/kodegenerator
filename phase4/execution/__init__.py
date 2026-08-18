"""Phase 4 AI-4 Execution Engine public contract."""

from .adapters import AdapterResult, ExecutionAdapter, StaticExecutionAdapter
from .engine import ExecutionEngine, ExecutionError, ExecutionRejected
from .models import (
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    GovernedDispatch,
    execution_id_for,
)
from .replay_ledger import (
    ClaimOutcome,
    ClaimOutcomeKind,
    ExecutionReplayLedger,
    InMemoryReplayLedger,
    LedgerRecord,
    LedgerStatus,
)

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
    "GovernedDispatch",
    "execution_id_for",
    "ClaimOutcome",
    "ClaimOutcomeKind",
    "ExecutionReplayLedger",
    "InMemoryReplayLedger",
    "LedgerRecord",
    "LedgerStatus",
]

__version__ = "4.1.0"
