"""Subcommand: declare a governed repository onboarding intent via Core API."""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

import requests

from generation.project_spec import ArchitectureKind, ProjectDefinition, SUPPORTED_STACKS
from phase4.onboarding import OnboardingPurpose

DEFAULT_API_URL = "http://127.0.0.1:8000"


def register_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "onboarding",
        help="Declare why a repository is being onboarded through the governed Control Plane API",
    )
    parser.add_argument("repository", help="Exact repository authority identity, e.g. repository:external/example")
    parser.add_argument(
        "--purpose",
        choices=[purpose.value for purpose in OnboardingPurpose],
        required=True,
    )
    parser.add_argument("--rationale", required=True, help="Human rationale for the selected purpose")
    parser.add_argument("--supersedes-intent-id", default=None)
    parser.add_argument("--command-id", default=None, help="Idempotency command ID; generated when omitted")
    parser.add_argument("--target-name", default=None)
    parser.add_argument(
        "--target-architecture",
        choices=[item.value for item in ArchitectureKind],
        default="hexagonal",
    )
    parser.add_argument(
        "--target-language",
        choices=sorted(SUPPORTED_STACKS),
        default=None,
    )
    parser.add_argument("--target-api", default=None)
    parser.add_argument("--target-database", default=None)
    parser.add_argument("--api-url", default=os.getenv("DOR_API_URL", DEFAULT_API_URL))
    parser.add_argument("--token", default=os.getenv("DOR_ACCESS_TOKEN"))
    parser.set_defaults(handler="onboarding")


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    purpose = OnboardingPurpose(args.purpose)
    target_stack: dict[str, Any] | None = None
    if purpose is OnboardingPurpose.MODERNIZE_REWRITE:
        required = {
            "--target-name": args.target_name,
            "--target-language": args.target_language,
            "--target-api": args.target_api,
            "--target-database": args.target_database,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "modernize_rewrite requires explicit target stack: " + ", ".join(missing)
            )
        target_stack = ProjectDefinition(
            name=args.target_name,
            architecture=args.target_architecture,
            language=args.target_language,
            api=args.target_api,
            database=args.target_database,
        ).model_dump(mode="json")
    elif any(
        value is not None
        for value in (
            args.target_name,
            args.target_language,
            args.target_api,
            args.target_database,
        )
    ):
        raise ValueError("target stack options are only valid for modernize_rewrite")

    return {
        "command_id": args.command_id or f"onboarding-{uuid.uuid4()}",
        "source_repository": args.repository,
        "purpose": purpose.value,
        "rationale": args.rationale,
        "target_stack": target_stack,
        "supersedes_intent_id": args.supersedes_intent_id,
    }


def execute(args: argparse.Namespace) -> int:
    token = (args.token or "").strip()
    if not token:
        print(
            "onboarding requires --token or DOR_ACCESS_TOKEN; authenticate through the Control Plane API first",
            file=sys.stderr,
        )
        return 2
    try:
        payload = build_payload(args)
    except (TypeError, ValueError) as exc:
        print(f"invalid onboarding command: {exc}", file=sys.stderr)
        return 2

    try:
        response = requests.post(
            f"{args.api_url.rstrip('/')}/api/v1/control-plane/onboarding-intents",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
            },
            json=payload,
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"onboarding API unavailable: {exc}", file=sys.stderr)
        return 1

    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text}
    if not response.ok:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        print(f"onboarding failed ({response.status_code}): {detail}", file=sys.stderr)
        return 1

    print(json.dumps(body, indent=2, sort_keys=True))
    return 0
