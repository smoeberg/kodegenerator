"""Phase 8 staging certification and reconciliation.

Staging certification answers three operational questions that Fase 8
requires to be automated, not tribal:

1. Is a given image digest certified for staging?
2. Can staging be rolled back to a *known* digest (one certified earlier)?
3. When a PR / image / deployment status is unknown, does reconciliation
   classify it as pending, drift, or rollback-required?

The module is deliberately dependency-free (stdlib only): it runs in CI, in
the staging operator's laptop, and inside the fire-drill scripts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class DeploymentSignature:
    """A deployable unit: repository, PR, image digest, and deployment id."""

    repo: str
    pr: int | None
    image: str
    digest: str
    deployment_id: str

    def fingerprint(self) -> str:
        canonical = json.dumps(
            {
                "repo": self.repo,
                "pr": self.pr,
                "image": self.image,
                "digest": self.digest,
                "deployment_id": self.deployment_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class CertificationLedger:
    """Append-only ledger of staging certifications, keyed by digest.

    ``digest`` is the immutable artifact identity. The ledger records when a
    digest was certified, by which gate run, and its evaluation status.

    Statuses:
    - ``certified``: passed integration + branch coverage; safe to deploy.
    - ``rollback``: previously certified, now rolled back (implicitly: the
      current staging digest supersedes it only when explicitly recorded).
    - ``rejected``: failed a gate; never eligible for staging.
    """

    entries: dict[str, dict[str, str]] = field(default_factory=dict)

    def certify(
        self, signature: DeploymentSignature, gate_run: str, now: str | None = None
    ) -> dict[str, str]:
        digest = signature.digest
        now = now or datetime.now(timezone.utc).isoformat()
        previous = self.entries.get(digest)
        if previous is not None:
            # Idempotent re-certification of the same digest+gate is allowed,
            # but a conflicting gate run is suspicious.
            if previous.get("gate_run") != gate_run:
                raise ValueError(
                    f"digest {digest} already certified by gate_run {previous['gate_run']}"
                )
            return previous
        entry = {
            "digest": digest,
            "repo": signature.repo,
            "pr": str(signature.pr) if signature.pr is not None else "main",
            "image": signature.image,
            "gate_run": gate_run,
            "status": "certified",
            "certified_at": now,
            "fingerprint": signature.fingerprint(),
        }
        self.entries[digest] = entry
        return entry

    def known_digest(self, digest: str) -> bool:
        return digest in self.entries

    def certified(self, digest: str) -> bool:
        entry = self.entries.get(digest)
        return entry is not None and entry["status"] == "certified"

    def latest_certified(self, image: str) -> str | None:
        """Return the most recently certified digest for an image."""
        candidates = [
            entry
            for entry in self.entries.values()
            if entry["image"] == image and entry["status"] == "certified"
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e["certified_at"])["digest"]


@dataclass(frozen=True)
class ReconciliationStatus:
    """Result of reconciling an unknown PR / image / deployment status."""

    classification: str  # PENDING | DRIFT | ROLLBACK_REQUIRED | MISMATCH | OK
    detail: str
    digest: str | None = None
    known: bool = False
    rollback_target: str | None = None

    def __bool__(self) -> bool:
        return self.classification == "OK"


def reconcile_unknown(
    ledger: CertificationLedger,
    observed: DeploymentSignature,
    expected_digest: str | None = None,
    deployment_state: str | None = None,
) -> ReconciliationStatus:
    """Classify an observed deployment against the certification ledger.

    ``observed.digest`` is what is actually running in staging.
    ``expected_digest`` is what the pipeline says should be running
    (defaults to the ledger's latest certified digest for the image).
    ``deployment_state`` is the reported deployment status from the PR /
    registry / deploy API if known (``None`` means unknown).

    Classifications:
    - ``OK``: observed digest is certified and matches expectation.
    - ``PENDING``: deployment status is unknown (no outcome recorded yet).
    - ``DRIFT``: observed digest is running but not expected (someone or
      something moved staging without a certification event).
    - ``ROLLBACK_REQUIRED``: the observed digest is uncertified and an older
      certified digest is available as a safe rollback target.
    - ``MISMATCH``: the observed digest is certified but does not match the
      expected digest (a *known* deployment is out of place).
    """
    observed_known = ledger.certified(observed.digest)
    expected = expected_digest or ledger.latest_certified(observed.image)

    if deployment_state is None and not observed_known:
        target = ledger.latest_certified(observed.image)
        return ReconciliationStatus(
            classification="PENDING",
            detail="deployment status unknown and observed digest is not certified",
            digest=observed.digest,
            known=False,
            rollback_target=target,
        )

    if observed_known:
        if expected is None or observed.digest == expected:
            return ReconciliationStatus(
                classification="OK",
                detail="observed digest is certified and matches expectation",
                digest=observed.digest,
                known=True,
                rollback_target=expected,
            )
        return ReconciliationStatus(
            classification="MISMATCH",
            detail=f"certified digest {observed.digest} is running but expected {expected}",
            digest=observed.digest,
            known=True,
            rollback_target=expected,
        )

    # observed digest is NOT certified: either pending, drift, or a rollback
    # candidate depending on the reported deployment state.
    if deployment_state == "deployed":
        target = ledger.latest_certified(observed.image)
        return ReconciliationStatus(
            classification="ROLLBACK_REQUIRED" if target else "DRIFT",
            detail=(
                f"uncertified digest {observed.digest} is deployed; "
                + (
                    f"rollback to certified digest {target}"
                    if target
                    else "no certified digest exists"
                )
            ),
            digest=observed.digest,
            known=False,
            rollback_target=target,
        )

    if deployment_state == "pending":
        target = ledger.latest_certified(observed.image)
        return ReconciliationStatus(
            classification="PENDING",
            detail=(
                f"deployment reported pending with uncertified digest {observed.digest}; "
                + (
                    "wait for pipeline outcome or roll back"
                    if target
                    else "no certified digest exists"
                )
            ),
            digest=observed.digest,
            known=False,
            rollback_target=target,
        )

    return ReconciliationStatus(
        classification="DRIFT",
        detail=f"observed uncertified digest {observed.digest} does not match expectation",
        digest=observed.digest,
        known=False,
        rollback_target=expected,
    )
