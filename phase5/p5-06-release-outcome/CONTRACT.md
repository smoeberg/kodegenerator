# P5-06 Release Outcome Contract

P5-06 records the observed outcome of a P5-05 release dispatch. It consumes an immutable `ReleaseDispatchRecord` and produces an immutable `ReleaseOutcomeRecord`.

Allowed statuses: `RELEASE_ACCEPTED`, `RELEASE_REJECTED`, `RELEASE_FAILED`.

P5-06 MUST NOT create or evaluate release eligibility, perform verification, create or modify verification authority, mutate upstream records, execute/retry/schedule releases, alter organization identity, or bypass the authoritative P3-20 verification reference.

The outcome MUST preserve the dispatch identity and complete upstream provenance, including finalization fingerprint and verification reference.

Outcome records are immutable and append-only. Reprocessing the same dispatch outcome with the same external reference MUST be idempotent. A conflicting outcome for the same dispatch and external reference MUST be rejected rather than silently replaced.

Serialization and outcome identity MUST be deterministic. Malformed dispatch records, missing identity/provenance, unsupported statuses, and inconsistent outcome identity MUST be rejected.

Retry policy, external side effects, release decisioning, verification, authorization, and eligibility creation remain outside P5-06.
