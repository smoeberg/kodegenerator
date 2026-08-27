from __future__ import annotations

import json
from pathlib import Path

from services.context_engine import ContextEngine
from services.task_compiler import TaskCompiler


def test_task_compiler_and_context_produce_generation_ready_package(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    services = repository / "services"
    services.mkdir(parents=True)
    (services / "clock.py").write_text(
        "from datetime import datetime\n\n"
        "class Clock:\n"
        "    def now(self) -> datetime:\n"
        "        return datetime.now()\n",
        encoding="utf-8",
    )
    (services / "storage.py").write_text(
        "class CounterStore:\n"
        "    def increment(self, key: str, expires_at: float) -> int:\n"
        "        raise NotImplementedError\n",
        encoding="utf-8",
    )
    requirement_path = tmp_path / "requirement.json"
    requirement_path.write_text(
        json.dumps(
            {
                "title": "Sliding Window Rate Limiter",
                "description": "Use the existing Clock and CounterStore contracts.",
                "acceptance_criteria": [
                    "Allow requests below the configured window limit",
                    "Reject requests after the configured limit is reached",
                    "Reset counters after the time window expires",
                ],
                "target_module": "services/rate_limiter.py",
            }
        ),
        encoding="utf-8",
    )

    context = ContextEngine(repository, token_budget=500).build_context(
        target_module="services/rate_limiter.py",
        query="Sliding window Clock CounterStore increment",
    )
    signatures = {record.qualified_name: record.signature for record in context.signatures}
    assert signatures["Clock.now"] == "def Clock.now(self) -> datetime"
    assert signatures["CounterStore.increment"] == (
        "def CounterStore.increment(self, key: str, expires_at: float) -> int"
    )
    assert context.estimated_tokens <= context.token_budget

    compiled = TaskCompiler(repository, context_token_budget=500).compile(requirement_path)
    assert len(compiled.test_specifications) == 3
    assert len({spec.test_id for spec in compiled.test_specifications}) == 3
    assert all(spec.test_name.startswith("test_") for spec in compiled.test_specifications)
    assert "Clock.now" in compiled.code_synthesizer.prompt
    assert "CounterStore.increment" in compiled.test_synthesizer.prompt
    assert compiled.requirement.target_module == "services/rate_limiter.py"
    repeated = TaskCompiler(repository, context_token_budget=500).compile(requirement_path)
    assert compiled.to_json() == repeated.to_json()
