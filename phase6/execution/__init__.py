"""Phase 6 execution isolation and audit contracts."""

from phase6.execution.audit import AuditSink, ExecutionAuditEvent, NullAuditSink, StructuredAuditLogger
from phase6.execution.process import BubblewrapProcessAdapter, ProcessSandboxUnavailable
from phase6.execution.sandbox import (
    ExecutionLimits,
    ExecutionResult,
    ExecutionSecurityContext,
    ExecutionSpec,
    InvalidExecutionSpec,
    Sandbox,
    SandboxAdapter,
    SandboxRegistry,
)

__all__ = [
    "AuditSink",
    "BubblewrapProcessAdapter",
    "ExecutionAuditEvent",
    "ExecutionLimits",
    "ExecutionResult",
    "ExecutionSecurityContext",
    "ExecutionSpec",
    "InvalidExecutionSpec",
    "NullAuditSink",
    "ProcessSandboxUnavailable",
    "Sandbox",
    "SandboxAdapter",
    "SandboxRegistry",
    "StructuredAuditLogger",
]

from .audit_harness import (
    AuditHarness,
    ChainIntegrityError,
    GENESIS_HASH,
    HashChainEntry,
)
