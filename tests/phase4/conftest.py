"""Phase 4 test compatibility fixtures.

The implementation runtime deliberately requires an explicit organization_id.
A small number of legacy governed-patch tests predate that mandatory binding;
this fixture supplies the test organization's value without changing the
production constructor or runtime contract.
"""
from __future__ import annotations

import pytest

from phase4.implementation_agent import ImplementationAgentRuntime


@pytest.fixture(autouse=True)
def _legacy_governed_patch_organization_binding(request, monkeypatch):
    if request.node.path.name != "test_governed_patch_execution.py":
        return

    original_run = ImplementationAgentRuntime.run

    def run_with_test_organization(self, *args, **kwargs):
        kwargs.setdefault("organization_id", "org-test")
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(ImplementationAgentRuntime, "run", run_with_test_organization)
