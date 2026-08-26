"""Phase 4 Council Deliberation and Dispute Protocol.

Orchestrates multi-agent deliberation cycles, evidence-backed disputes,
and consensus threshold evaluations.
"""

from .dispute import DisputeProtocol, DisputeProtocolError
from .execution_events import (
    CouncilEventBindingError,
    CouncilFailureEventHandler,
    execution_failure_event_from_result,
)
from .models import Dispute, DisputeStatus, SessionState, Vote
from .runtime_models import (
    CouncilOutboxEvent,
    CouncilRuntimeEventType,
    CouncilSessionBinding,
    ExecutionFailedEvent,
    PersistedDeliberation,
)
from .session import DeliberationError, DeliberationSession
from .store import (
    CouncilConflictError,
    CouncilNotFoundError,
    CouncilStore,
    CouncilStoreError,
)

__all__ = [
    "CouncilConflictError",
    "CouncilEventBindingError",
    "CouncilFailureEventHandler",
    "CouncilNotFoundError",
    "CouncilOutboxEvent",
    "CouncilRuntimeEventType",
    "CouncilSessionBinding",
    "CouncilStore",
    "CouncilStoreError",
    "DeliberationError",
    "DeliberationSession",
    "Dispute",
    "DisputeProtocol",
    "DisputeProtocolError",
    "DisputeStatus",
    "ExecutionFailedEvent",
    "PersistedDeliberation",
    "SessionState",
    "Vote",
    "execution_failure_event_from_result",
]
