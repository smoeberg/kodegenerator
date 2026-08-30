#!/usr/bin/env python3
"""Phase 8 staging reconciliation CLI.

The fire-drill and on-call operator runs:

    python ci/staging/reconcile_cli.py status \
        --repo smoeberg/kodegenerator \
        --image ghcr.io/smoeberg/kodegenerator \
        --digest sha256:zzz \
        --deployment-state deployed \
        [--ledger ci/staging/ledger.json]

It answers, in one command, the Fase 8 question: is this unknown
PR/image/deployment status safe, pending, drifting, or rollback-required?

Also supports:
    certify --repo ... --image ... --digest sha256:aaa --gate-run run-7
    rollback --repo ... --image ... [--digest sha256:aaa]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ci.staging.staging_certification import (
    CertificationLedger,
    DeploymentSignature,
    reconcile_unknown,
)

DEFAULT_LEDGER = Path(__file__).parent / "ledger.json"


def load_ledger(path: Path) -> CertificationLedger:
    ledger = CertificationLedger()
    if path.exists():
        raw = path.read_text()
        if raw.strip():
            ledger.entries = json.loads(raw)
    return ledger


def save_ledger(ledger: CertificationLedger, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ledger.entries, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="reconcile_cli", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="classify an observed deployment")
    status.add_argument("--repo", required=True)
    status.add_argument("--image", required=True)
    status.add_argument("--digest", required=True)
    status.add_argument(
        "--deployment-state", choices=["deployed", "pending", None], default=None
    )
    status.add_argument("--expected-digest")
    status.add_argument("--deployment-id", default="unknown")
    status.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    certify = sub.add_parser("certify", help="certify a digest for staging")
    certify.add_argument("--repo", required=True)
    certify.add_argument("--image", required=True)
    certify.add_argument("--digest", required=True)
    certify.add_argument("--gate-run", required=True)
    certify.add_argument("--pr")
    certify.add_argument("--deployment-id", default="certified")
    certify.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    rollback = sub.add_parser(
        "rollback", help="print the known rollback target for an image"
    )
    rollback.add_argument("--repo", required=True)
    rollback.add_argument("--image", required=True)
    rollback.add_argument("--digest")
    rollback.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)

    args = parser.parse_args(argv)

    if args.command == "status":
        ledger = load_ledger(args.ledger)
        observed = DeploymentSignature(
            repo=args.repo,
            pr=None,
            image=args.image,
            digest=args.digest,
            deployment_id=args.deployment_id,
        )
        result = reconcile_unknown(
            ledger,
            observed,
            expected_digest=args.expected_digest,
            deployment_state=args.deployment_state,
        )
        print(
            json.dumps(
                {
                    "classification": result.classification,
                    "detail": result.detail,
                    "digest": result.digest,
                    "known": result.known,
                    "rollback_target": result.rollback_target,
                },
                indent=2,
            )
        )
        return 0 if result.classification in ("OK", "PENDING") else 1

    if args.command == "certify":
        ledger = load_ledger(args.ledger)
        signature = DeploymentSignature(
            repo=args.repo,
            pr=int(args.pr) if args.pr else None,
            image=args.image,
            digest=args.digest,
            deployment_id=args.deployment_id,
        )
        entry = ledger.certify(signature, gate_run=args.gate_run)
        save_ledger(ledger, args.ledger)
        print(
            json.dumps(
                {
                    "certified": entry["digest"],
                    "status": entry["status"],
                    "gate_run": entry["gate_run"],
                },
                indent=2,
            )
        )
        return 0

    if args.command == "rollback":
        ledger = load_ledger(args.ledger)
        if args.digest:
            target = args.digest if ledger.certified(args.digest) else None
            known = ledger.certified(args.digest)
        else:
            target = ledger.latest_certified(args.image)
            known = target is not None
        if not known:
            print(
                json.dumps(
                    {"error": "no certified rollback target", "rollback_target": None},
                    indent=2,
                )
            )
            return 1
        print(json.dumps({"rollback_target": target, "known": True}, indent=2))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
