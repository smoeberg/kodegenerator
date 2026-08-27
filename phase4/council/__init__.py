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
from .orchestrator import (
    CouncilOrchestrationError,
    CouncilOrchestrator,
    CouncilOrchestratorResult,
    CouncilProvider,
    CouncilProviderError,
    CouncilProviderResponseError,
    CouncilRiskEvaluator,
    CouncilStartError,
    DefaultCouncilRiskEvaluator,
    DeliberationConfig,
)
from .roles import (
    ROLE_PERSONAS,
    CouncilAgenda,
    CouncilDisputeProposal,
    CouncilDisputeResolution,
    CouncilOrchestrationOutcome,
    CouncilRole,
    CouncilRoleAssignment,
    CouncilTurnDecision,
    CouncilTurnKind,
    CouncilTurnRequest,
    CouncilTurnResponse,
    RolePersona,
)
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
    "ROLE_PERSONAS",
    "CouncilAgenda",
    "CouncilConflictError",
    "CouncilDisputeProposal",
    "CouncilDisputeResolution",
    "CouncilEventBindingError",
    "CouncilFailureEventHandler",
    "CouncilNotFoundError",
    "CouncilOrchestrationError",
    "CouncilOrchestrationOutcome",
    "CouncilOrchestrator",
    "CouncilOrchestratorResult",
    "CouncilOutboxEvent",
    "CouncilProvider",
    "CouncilProviderError",
    "CouncilProviderResponseError",
    "CouncilRiskEvaluator",
    "CouncilRole",
    "CouncilRoleAssignment",
    "CouncilRuntimeEventType",
    "CouncilSessionBinding",
    "CouncilStartError",
    "CouncilStore",
    "CouncilStoreError",
    "CouncilTurnDecision",
    "CouncilTurnKind",
    "CouncilTurnRequest",
    "CouncilTurnResponse",
    "DefaultCouncilRiskEvaluator",
    "DeliberationConfig",
    "DeliberationError",
    "DeliberationSession",
    "Dispute",
    "DisputeProtocol",
    "DisputeProtocolError",
    "DisputeStatus",
    "ExecutionFailedEvent",
    "PersistedDeliberation",
    "RolePersona",
    "SessionState",
    "Vote",
    "execution_failure_event_from_result",
]
