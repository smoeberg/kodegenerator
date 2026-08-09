# P5-02 Verification Handoff

P5-02 is the integrity boundary between P5-01 execution and P3-20 independent verification.

It accepts only `SUBMITTED` work, binds the exact P5-00 contract and submission fingerprints, preserves candidate evidence, routes only to `p3-20`, and binds the returned authoritative decision.

It never creates or infers a verification decision.
