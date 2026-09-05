"""CLI tests for the governed onboarding entrypoint."""
from __future__ import annotations

import json

from cli.commands import onboarding
from cli.main import build_parser


class _Response:
    ok = True
    status_code = 201
    text = ""

    def json(self):
        return {
            "command_id": "cmd-1",
            "replayed": False,
            "intent": {
                "intent_id": "a" * 64,
                "organization_id": "org-a",
                "declared_by": "alice",
            },
        }


def _args(*extra: str):
    return build_parser().parse_args(
        [
            "onboarding",
            "repository:external/example",
            "--purpose",
            "extend",
            "--rationale",
            "Extend the existing system.",
            "--command-id",
            "cmd-1",
            "--token",
            "secret-token",
            *extra,
        ]
    )


def test_payload_contains_semantic_intent_but_no_actor_or_tenant() -> None:
    payload = onboarding.build_payload(_args())

    assert payload["command_id"] == "cmd-1"
    assert payload["source_repository"] == "repository:external/example"
    assert payload["purpose"] == "extend"
    assert payload["target_stack"] is None
    assert "organization_id" not in payload
    assert "declared_by" not in payload
    assert "declared_at" not in payload


def test_rewrite_requires_and_serializes_explicit_target_stack() -> None:
    args = build_parser().parse_args(
        [
            "onboarding",
            "repository:external/example",
            "--purpose",
            "modernize_rewrite",
            "--rationale",
            "Preserve behavior on Rust.",
            "--target-name",
            "modernized-app",
            "--target-language",
            "rust",
            "--target-api",
            "axum",
            "--target-database",
            "postgresql",
            "--token",
            "secret-token",
        ]
    )
    payload = onboarding.build_payload(args)
    assert payload["target_stack"] == {
        "name": "modernized-app",
        "architecture": "hexagonal",
        "language": "rust",
        "api": "axum",
        "database": "postgresql",
    }


def test_execute_posts_only_to_canonical_control_plane_endpoint(monkeypatch, capsys) -> None:
    captured = {}

    def post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _Response()

    monkeypatch.setattr(onboarding.requests, "post", post)

    result = onboarding.execute(_args("--api-url", "https://dor.example"))

    assert result == 0
    assert captured["url"] == "https://dor.example/api/v1/control-plane/onboarding-intents"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert "organization_id" not in captured["json"]
    rendered = json.loads(capsys.readouterr().out)
    assert rendered["intent"]["declared_by"] == "alice"


def test_execute_fails_closed_without_bearer_token(capsys) -> None:
    args = _args()
    args.token = None

    assert onboarding.execute(args) == 2
    assert "requires --token or DOR_ACCESS_TOKEN" in capsys.readouterr().err
