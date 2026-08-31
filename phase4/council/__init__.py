"""Phase 4 Council Deliberation and Dispute Protocol.

Orchestrates multi-agent deliberation cycles, evidence-backed disputes,
and consensus threshold evaluations.
"""

from phase4.verification.allocation_selector import (
    CouncilRunSelection,
    CouncilSelectionError,
    DeterministicCouncilSelector,
    FrozenCouncilAssignment,
    SelectionCandidate,
    SelectionReceipt,
    SelectionRequestContext,
)

from .configuration import (
    AllocationMember,
    AutonomyLevel,
    CouncilRoleDefinition,
    CouncilTemplate,
    IndependenceLevel,
    ProtocolFunction,
    RoleAllocationPool,
    TemplateStage,
)
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
    "AllocationMember",
    "AutonomyLevel",
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
    "CouncilRoleDefinition",
    "CouncilRole",
    "CouncilRoleAssignment",
    "CouncilRuntimeEventType",
    "CouncilRunSelection",
    "CouncilSelectionError",
    "CouncilSessionBinding",
    "CouncilStartError",
    "CouncilStore",
    "CouncilStoreError",
    "CouncilTurnDecision",
    "CouncilTurnKind",
    "CouncilTurnRequest",
    "CouncilTurnResponse",
    "CouncilTemplate",
    "DefaultCouncilRiskEvaluator",
    "DeterministicCouncilSelector",
    "DeliberationConfig",
    "DeliberationError",
    "DeliberationSession",
    "Dispute",
    "DisputeProtocol",
    "DisputeProtocolError",
    "DisputeStatus",
    "ExecutionFailedEvent",
    "FrozenCouncilAssignment",
    "IndependenceLevel",
    "PersistedDeliberation",
    "ProtocolFunction",
    "RoleAllocationPool",
    "RolePersona",
    "SessionState",
    "SelectionCandidate",
    "SelectionRequestContext",
    "SelectionReceipt",
    "TemplateStage",
    "Vote",
    "execution_failure_event_from_result",
]
