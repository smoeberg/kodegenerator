"""Phase 4 AI-4 Execution Engine public contract."""

from .adapters import AdapterResult, ExecutionAdapter, StaticExecutionAdapter
from .durable_ledger import ExecutionReplayLedgerModel, SqlAlchemyReplayLedger
from .engine import ExecutionEngine, ExecutionError, ExecutionRejected
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
    "StaleClaimTokenError",
    "ExecutionReplayLedgerModel",
    "SqlAlchemyReplayLedger",
]

__version__ = "4.1.0"
