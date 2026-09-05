"""Pure GUI payload tests for repository onboarding."""
from __future__ import annotations

import pytest

from dashboard.onboarding import build_onboarding_payload


def test_extend_payload_never_contains_trusted_identity_fields() -> None:
    payload = build_onboarding_payload(
        command_id="cmd-1",
        source_repository="repository:external/example",
        purpose="extend",
        rationale="Extend the current implementation.",
    )

    assert payload == {
        "command_id": "cmd-1",
        "source_repository": "repository:external/example",
        "purpose": "extend",
        "rationale": "Extend the current implementation.",
        "target_stack": None,
        "supersedes_intent_id": None,
    }
    assert "organization_id" not in payload
    assert "declared_by" not in payload


def test_rewrite_payload_uses_canonical_project_definition() -> None:
    payload = build_onboarding_payload(
        command_id="cmd-2",
        source_repository="repository:external/example",
        purpose="modernize_rewrite",
        rationale="Preserve behavior on a new stack.",
        target_name="modernized-app",
        target_architecture="hexagonal",
        target_language="rust",
        target_api="axum",
        target_database="postgresql",
    )

    assert payload["target_stack"] == {
        "name": "modernized-app",
        "architecture": "hexagonal",
        "language": "rust",
        "api": "axum",
        "database": "postgresql",
    }


def test_non_rewrite_rejects_target_stack() -> None:
    with pytest.raises(ValueError, match="kun tilladt"):
        build_onboarding_payload(
            command_id="cmd-3",
            source_repository="repository:external/example",
            purpose="audit_only",
            rationale="Audit without implementation.",
            target_name="should-not-exist",
        )
