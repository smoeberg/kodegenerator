# Bot evaluation and learning

Evaluation is evidence, not authority. A producer assignment is evaluated by a
separately frozen evaluator assignment at the independence level configured in
the rubric.

The runtime order is fixed:

1. Validate tenant, subject fingerprint, rubric fingerprint, base SHA, and
   producer/evaluator snapshots.
2. Run deterministic checks through the existing verification boundaries.
3. Stop on a deterministic hard failure. No model is asked to reinterpret it.
4. Validate evaluator independence.
5. Run semantic criteria through `GovernedLLMRuntime` using the selected
   provider connection. LibreChat is an ordinary OpenAI-compatible connection;
   it receives no special authority.
6. Persist an immutable evaluation record.
7. Append empirical observations. Corrections append a new observation linked
   through `supersedes_observation_id`; historical facts are never edited.
8. Build performance snapshots through an exact ledger position. Later events
   cannot alter an existing snapshot.

Rubrics, evaluation records, observations, and snapshots are tenant-scoped.
PostgreSQL enables and forces RLS; stores also apply explicit organization
predicates so SQLite tests retain the same visibility contract.

Provider credentials are not part of these records. Only non-secret provider,
model, prompt, request, token, and fingerprint provenance may be retained.
