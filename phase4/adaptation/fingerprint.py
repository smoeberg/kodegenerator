"""Strategy fingerprinting and anti-tunneling failure intelligence for AI agents."""
from __future__ import annotations

import hashlib
from typing import List, Dict
from pydantic import BaseModel, Field


class FailureRecord(BaseModel):
    task_id: str
    strategy_signature: str
    error_message: str
    attempt_number: int


class AdaptationTracker(BaseModel):
    failure_history: List[FailureRecord] = Field(default_factory=list)
    signature_counts: Dict[str, int] = Field(default_factory=dict)
    tunnel_threshold: int = 2  # Max retries with identical strategy before forced pivot

    def compute_signature(self, prompt_summary: str, chosen_tool: str, key_parameters: str) -> str:
        raw = f"{prompt_summary}:{chosen_tool}:{key_parameters}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def record_failure(self, task_id: str, signature: str, error_msg: str) -> int:
        record = FailureRecord(
            task_id=task_id,
            strategy_signature=signature,
            error_message=error_msg,
            attempt_number=self.signature_counts.get(signature, 0) + 1
        )
        self.failure_history.append(record)
        self.signature_counts[signature] = record.attempt_number
        return record.attempt_number

    def is_tunneling(self, signature: str) -> bool:
        """Returns True if the agent is stuck in a loop using the same failing strategy."""
        return self.signature_counts.get(signature, 0) >= self.tunnel_threshold

    def get_pivot_recommendation(self, signature: str) -> str:
        if self.is_tunneling(signature):
            return "TUNNELING_DETECTED: Strategy has failed repeatedly. Forcing dialectical pivot to alternative hypothesis or role rotation."
        return "PROCEED: Strategy within acceptable variance."
