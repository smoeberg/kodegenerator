from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from resolution_models import (
    ReleaseResolutionRecord,
    ResolutionDisposition,
    ResolutionError,
    ResolutionPolicy,
)


_KNOWN_STATUSES = {"RECONCILED", "OUTCOME_MISSING", "MISMATCH"}


def _value(record: object, name: str) -> object:
    try:
        return getattr(record, name)
    except AttributeError as exc:
        raise ResolutionError(f"missing required field: {name}") from exc


def _require(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ResolutionError(f"missing required provenance: {name}")
    return value


def _policy_fingerprint(policy: ResolutionPolicy) -> str:
    payload = json.dumps(policy.canonical(), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


class ReleaseResolver:
    """Pure P5-08 policy resolver; it performs no execution or external I/O."""

    def resolve(
        self,
        reconciliation: object,
        dispatch: object,
        outcome: object | None,
        *,
        policy: ResolutionPolicy | None = None,
        now: datetime | None = None,
    ) -> ReleaseResolutionRecord:
        policy = policy or ResolutionPolicy()

        reconciliation_id = _require(_value(reconciliation, "reconciliation_id"), "reconciliation_id")
        reconciliation_fingerprint = _require(
            _value(reconciliation, "reconciliation_fingerprint"), "reconciliation_fingerprint"
        )
        dispatch_id = _require(_value(reconciliation, "dispatch_id"), "reconciliation.dispatch_id")
        finalization = _require(
            _value(reconciliation, "finalization_fingerprint"), "reconciliation.finalization_fingerprint"
        )
        status = _value(reconciliation, "status")
        if not isinstance(status, str) or status not in _KNOWN_STATUSES:
            raise ResolutionError("unknown reconciliation status")

        self._validate_dispatch_chain(dispatch, dispatch_id, finalization)

        reconciliation_outcome_id = _value(reconciliation, "outcome_id")
        if status == "OUTCOME_MISSING":
            if reconciliation_outcome_id is not None:
                raise ResolutionError("OUTCOME_MISSING cannot contain an outcome_id")
            if outcome is not None:
                raise ResolutionError("OUTCOME_MISSING cannot supply an outcome")
            if policy.outcome_missing is None:
                raise ResolutionError("OUTCOME_MISSING requires explicit policy")
            disposition = policy.outcome_missing
            outcome_id = None
        else:
            if not reconciliation_outcome_id:
                raise ResolutionError("observed reconciliation requires outcome_id")
            if outcome is None:
                raise ResolutionError("observed reconciliation requires outcome")
            outcome_id = _require(_value(outcome, "outcome_id"), "outcome.outcome_id")
            self._validate_outcome_chain(outcome, dispatch_id, finalization, dispatch)
            if outcome_id != reconciliation_outcome_id:
                raise ResolutionError("outcome identity conflicts with reconciliation")

            if status == "RECONCILED":
                accepted = _value(outcome, "accepted")
                if accepted is not True:
                    raise ResolutionError("RECONCILED outcome is not accepted")
                disposition = ResolutionDisposition.NO_ACTION
            else:
                disposition = policy.mismatch or ResolutionDisposition.ESCALATION_REQUIRED
                if disposition is ResolutionDisposition.RETRY_REQUESTED:
                    raise ResolutionError("MISMATCH cannot request automatic retry")

        timestamp = now or datetime.now(timezone.utc)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        policy_fp = _policy_fingerprint(policy)
        identity_payload = {
            "reconciliation_id": reconciliation_id,
            "reconciliation_fingerprint": reconciliation_fingerprint,
            "dispatch_id": dispatch_id,
            "outcome_id": outcome_id,
            "finalization_fingerprint": finalization,
            "verifier_id": _require(_value(dispatch, "verifier_id"), "dispatch.verifier_id"),
            "release_id": _require(_value(dispatch, "release_id"), "dispatch.release_id"),
            "policy_fingerprint": policy_fp,
        }
        resolution_id = sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return ReleaseResolutionRecord(
            resolution_id=resolution_id,
            reconciliation_id=reconciliation_id,
            reconciliation_fingerprint=reconciliation_fingerprint,
            dispatch_id=dispatch_id,
            outcome_id=outcome_id,
            finalization_fingerprint=finalization,
            verifier_id=identity_payload["verifier_id"],
            release_id=identity_payload["release_id"],
            disposition=disposition,
            policy_fingerprint=policy_fp,
            resolved_at=timestamp,
        )

    @staticmethod
    def _validate_dispatch_chain(dispatch: object, dispatch_id: str, finalization: str) -> None:
        if _require(_value(dispatch, "dispatch_id"), "dispatch.dispatch_id") != dispatch_id:
            raise ResolutionError("dispatch identity conflicts with reconciliation")
        if _require(_value(dispatch, "finalization_fingerprint"), "dispatch.finalization_fingerprint") != finalization:
            raise ResolutionError("finalization provenance conflicts with reconciliation")
        _require(_value(dispatch, "verifier_id"), "dispatch.verifier_id")
        _require(_value(dispatch, "release_id"), "dispatch.release_id")

    @staticmethod
    def _validate_outcome_chain(
        outcome: object, dispatch_id: str, finalization: str, dispatch: object
    ) -> None:
        if _require(_value(outcome, "dispatch_id"), "outcome.dispatch_id") != dispatch_id:
            raise ResolutionError("outcome identity conflicts with dispatch")
        if _require(_value(outcome, "finalization_fingerprint"), "outcome.finalization_fingerprint") != finalization:
            raise ResolutionError("outcome provenance conflicts with dispatch")
        if _require(_value(outcome, "verifier_id"), "outcome.verifier_id") != _value(dispatch, "verifier_id"):
            raise ResolutionError("outcome verifier provenance conflicts with dispatch")
        if _require(_value(outcome, "release_id"), "outcome.release_id") != _value(dispatch, "release_id"):
            raise ResolutionError("outcome release identity conflicts with dispatch")
