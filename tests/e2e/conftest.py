"""Shared fixtures for swarm E2E integration tests.

All fixtures favour in-memory / local temp resources so the suite stays
deterministic and fast (no real LLM calls, no network).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Sequence

import pytest

from services.security_sentinel import ScanContext, SecuritySentinel
from services.swarm_orchestrator import SwarmOrchestrator
from services.swarm_persistence import SQLiteTaskQueue
from services.swarm_task_queue import QueuedTask, QueuedTaskStatus, SwarmTaskQueue
from services.worker_agent_daemon import WorkerAgent


# ---------------------------------------------------------------------------
# Capability profile used by parallel field workers
# ---------------------------------------------------------------------------

FULL_CAPS: List[str] = [
    "cap.domain.modeling",
    "cap.architecture.design",
    "cap.code.generation",
    "cap.contract.design",
    "cap.implementation",
    "cap.ast.write",
    "cap.run.tests",
    "cap.verification",
    "cap.sandbox.testing",
    "cap.security.audit",
    "cap.penetration.test",
    "cap.code.review",
    "cap.documentation",
    "code",
    "security",
]


def make_unified_diff(source: str, path: str = "generated/module.py") -> str:
    """Build a minimal unified diff that SecuritySentinel can parse."""
    lines = source.splitlines()
    header = [
        "--- /dev/null",
        f"+++ b/{path}",
        f"@@ -0,0 +1,{len(lines)} @@",
    ]
    return "\n".join(header + [f"+{line}" for line in lines]) + "\n"


SAFE_SOURCE = '''\
"""Safe governed module."""

def run(payload: dict | None = None) -> dict:
    data = dict(payload or {})
    data["status"] = "ok"
    return data
'''

UNSAFE_SOURCE = '''\
"""Unsafe module using shell execution."""

def run(payload: dict | None = None) -> dict:
    __import__("os").system("echo pwned")
    return {"status": "bad"}
'''


@dataclass
class PatchOutcome:
    approved: bool
    task_id: str
    source_code: str
    patch_diff: str
    lines: int
    path: str
    security_blocked: bool = False
    error: Optional[str] = None


class DeterministicSynthesizer:
    """In-memory synthesizer that returns safe or unsafe patches by policy."""

    def __init__(
        self,
        *,
        unsafe_task_ids: Optional[set[str]] = None,
        unsafe_once: Optional[set[str]] = None,
        source_for: Optional[Callable[[QueuedTask], str]] = None,
    ) -> None:
        self.unsafe_task_ids = set(unsafe_task_ids or ())
        self.unsafe_once = set(unsafe_once or ())
        self._attempted: set[str] = set()
        self.source_for = source_for
        self.calls: List[str] = []

    def synthesize(self, task: QueuedTask) -> dict[str, Any]:
        self.calls.append(task.task_id)
        if self.source_for is not None:
            source = self.source_for(task)
        elif task.task_id in self.unsafe_task_ids:
            source = UNSAFE_SOURCE
        elif task.task_id in self.unsafe_once and task.task_id not in self._attempted:
            self._attempted.add(task.task_id)
            source = UNSAFE_SOURCE
        else:
            source = SAFE_SOURCE
        path = f"generated/{task.task_id}.py"
        return {
            "task_id": task.task_id,
            "artifact": path,
            "path": path,
            "lines": len(source.splitlines()),
            "source_code": source,
            "patch_diff": make_unified_diff(source, path),
            "status": "synthesized",
        }


class SentinelGateSynthesizer:
    """Synthesizer decorator that fails closed when SecuritySentinel blocks."""

    def __init__(
        self,
        inner: DeterministicSynthesizer,
        sentinel: SecuritySentinel,
        *,
        repository_root: Path,
    ) -> None:
        self.inner = inner
        self.sentinel = sentinel
        self.repository_root = repository_root
        self.blocked: List[str] = []
        self.approved: List[str] = []

    def synthesize(self, task: QueuedTask) -> dict[str, Any]:
        result = self.inner.synthesize(task)
        patch = result.get("patch_diff") or make_unified_diff(
            result.get("source_code", SAFE_SOURCE),
            result.get("path", f"generated/{task.task_id}.py"),
        )
        context = ScanContext(
            repository_root=self.repository_root,
            allowed_paths=["generated", "src", "services", "domain", "tests"],
            branch_name=f"worker/{task.task_id}",
            target_branch="main",
        )
        report = self.sentinel.scan_patch(patch, context)
        is_safe, blocking = self.sentinel.check_merge_safety(report)
        if not is_safe:
            self.blocked.append(task.task_id)
            rules = ", ".join(sorted({f.rule for f in blocking})) or "security"
            raise RuntimeError(
                f"SecuritySentinel blocked task {task.task_id}: {rules}"
            )
        self.approved.append(task.task_id)
        result["security_clean"] = True
        result["security_findings"] = len(report.findings)
        return result


def drain_queue_with_workers(
    queue: Any,
    *,
    n_workers: int = 3,
    capabilities: Sequence[str] = FULL_CAPS,
    synthesizer: Any = None,
    max_cycles: int = 50,
    poll_interval: float = 0.01,
    heartbeat_interval: float = 60.0,
) -> List[WorkerAgent]:
    """Run *n_workers* WorkerAgents until the queue has no pending/claimed work."""

    agents: List[WorkerAgent] = []
    for i in range(n_workers):
        agents.append(
            WorkerAgent(
                worker_id=f"e2e-worker-{i + 1:02d}",
                capabilities=list(capabilities),
                queue=queue,
                synthesizer=synthesizer,
                poll_interval=poll_interval,
                heartbeat_interval=heartbeat_interval,
                max_idle_cycles=max_cycles,
            )
        )

    def _run(agent: WorkerAgent) -> None:
        agent.run()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        list(pool.map(_run, agents))
    return agents


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Minimal repository root for SecuritySentinel path checks."""
    (tmp_path / "generated").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def security_sentinel(tmp_repo: Path) -> SecuritySentinel:
    return SecuritySentinel(
        repository_root=tmp_repo,
        allowed_paths=["generated", "src", "services", "domain", "tests", "phase"],
    )


@pytest.fixture
def memory_queue() -> SwarmTaskQueue:
    return SwarmTaskQueue(lease_seconds=120)


@pytest.fixture
def sqlite_queue(tmp_path: Path) -> SQLiteTaskQueue:
    q = SQLiteTaskQueue(tmp_path / "swarm-e2e.db", lease_seconds=120)
    yield q
    q.close()


@pytest.fixture
def swarm_orchestrator(tmp_repo: Path, memory_queue: SwarmTaskQueue) -> SwarmOrchestrator:
    return SwarmOrchestrator(repo_root=tmp_repo, task_queue=memory_queue)
