"""End-to-End Pipeline Runner enforcing the master architecture contract:
Ingestion -> Immutable Context Packet -> Durable Council -> DecisionReadiness ->
Authority -> Sandbox Execution -> Independent Verification -> Branch + Draft PR.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional

@dataclass
class ContextPacket:
    organization_id: str
    task_id: str
    correlation_id: str
    revision_binding: str
    idempotency_key: str
    payload: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

@dataclass
class PipelineResult:
    task_id: str
    correlation_id: str
    status: str  # "SUCCESS", "DENIED", "VERIFICATION_FAILED", "PIVOT_REQUIRED"
    branch_name: Optional[str] = None
    draft_pr_url: Optional[str] = None
    audit_trail: List[str] = field(default_factory=list)

class E2EPipelineRunner:
    """Orchestrates the entire governed agent pipeline from ingestion to Draft PR."""

    def __init__(self, council_orchestrator: Any, authority_gate: Any, verifier: Any, git_adapter: Any):
        self.council_orchestrator = council_orchestrator
        self.authority_gate = authority_gate
        self.verifier = verifier
        self.git_adapter = git_adapter
        self._idempotency_cache: Dict[str, PipelineResult] = {}

    def execute(self, packet: ContextPacket) -> PipelineResult:
        audit = []
        audit.append(f"Received context packet for task {packet.task_id} [corr: {packet.correlation_id}]")

        # 1. Idempotency Check
        if packet.idempotency_key in self._idempotency_cache:
            audit.append(f"Idempotency cache hit for key {packet.idempotency_key}. Returning cached result.")
            cached = self._idempotency_cache[packet.idempotency_key]
            cached.audit_trail = audit + cached.audit_trail
            return cached

        # 2. Durable Council Deliberation
        audit.append("Initiating Durable Council Deliberation...")
        try:
            council_res = self.council_orchestrator.run_deliberation(
                task_id=packet.task_id,
                task_description=packet.payload.get("description", "Legacy refactoring task")
            )
            audit.append(f"Council deliberation completed. Result: {council_res.status}")
        except Exception as e:
            audit.append(f"Council deliberation failed with exception: {str(e)}")
            res = PipelineResult(task_id=packet.task_id, correlation_id=packet.correlation_id, status="DENIED", audit_trail=audit)
            self._idempotency_cache[packet.idempotency_key] = res
            return res

        if council_res.status != "DECISION_READY" or not council_res.top_hypothesis:
            audit.append("Council failed to reach consensus or denied the hypothesis. Stopping pipeline (Fail-Closed).")
            res = PipelineResult(task_id=packet.task_id, correlation_id=packet.correlation_id, status="DENIED", audit_trail=audit)
            self._idempotency_cache[packet.idempotency_key] = res
            return res

        # 3. DecisionReadiness & Authority Check
        audit.append("Evaluating DecisionReadiness and Authority grant...")
        # Check authority gate (fail-closed)
        grant = self.authority_gate.evaluate(
            organization_id=packet.organization_id,
            hypothesis=council_res.top_hypothesis,
            confidence=council_res.top_hypothesis.confidence
        )
        if not grant or not grant.get("approved", False):
            audit.append("Authority grant denied or expired. Halting execution.")
            res = PipelineResult(task_id=packet.task_id, correlation_id=packet.correlation_id, status="DENIED", audit_trail=audit)
            self._idempotency_cache[packet.idempotency_key] = res
            return res

        audit.append("Authority grant approved. Proceeding to Sandbox Execution.")

        # 4. Sandbox Execution (Isolated Patch Application)
        branch_name = f"agent-fix-{packet.task_id}-{uuid.uuid4().hex[:6]}"
        audit.append(f"Created isolated branch: {branch_name}")
        
        patch_applied = self.git_adapter.apply_patch(branch_name, packet.payload.get("patch", ""))
        if not patch_applied:
            audit.append("Sandbox patch application failed.")
            res = PipelineResult(task_id=packet.task_id, correlation_id=packet.correlation_id, status="VERIFICATION_FAILED", audit_trail=audit)
            self._idempotency_cache[packet.idempotency_key] = res
            return res

        # 5. Independent Verification
        audit.append("Running independent verification (tests & static analysis)...")
        verification_passed = self.verifier.verify(branch_name)
        if not verification_passed:
            audit.append("Independent verification failed! Triggering Anti-Tube / Pivot event.")
            res = PipelineResult(task_id=packet.task_id, correlation_id=packet.correlation_id, status="VERIFICATION_FAILED", audit_trail=audit)
            self._idempotency_cache[packet.idempotency_key] = res
            return res

        audit.append("Verification passed successfully.")

        # 6. Branch + Commit + Draft PR (Never direct to main)
        audit.append("Creating Draft PR...")
        pr_url = self.git_adapter.create_draft_pr(
            branch_name=branch_name,
            title=f"AI Refactoring: {packet.task_id}",
            body=f"Automated refactoring via governed multi-agent council. Task: {packet.task_id}"
        )

        res = PipelineResult(
            task_id=packet.task_id,
            correlation_id=packet.correlation_id,
            status="SUCCESS",
            branch_name=branch_name,
            draft_pr_url=pr_url,
            audit_trail=audit
        )
        self._idempotency_cache[packet.idempotency_key] = res
        return res
