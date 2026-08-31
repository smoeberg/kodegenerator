# Factory work packages and candidate branches

Revision `022_factory_work_candidates` introduces the durable boundary between
approved factory contracts and parallel implementation workers.

## Invariants

- A work package is immutable apart from its fail-closed status transition and
  optimistic-lock version.
- Every package is bound to exact requirements, architecture, contract, policy,
  allocation, and Git base fingerprints.
- The synthesizer creates a deterministic DAG. Overlapping write scopes are
  serialized instead of being scheduled concurrently.
- The queue message contains only tenant, package identity, and fingerprint.
  Workers must load the authoritative package from the database.
- A candidate starts from the package's exact base SHA in an isolated worktree.
- Changed paths must remain inside the write scope and outside denied paths.
- Candidate commits, head SHA, patch fingerprint, paths, and attestations are
  recorded as immutable evidence.
- Candidate branch pushes use the terminal side-effect coordinator. An existing
  branch is accepted only when its remote head equals the attested head.
- A candidate selection can reference only durable candidates bound to the same
  package fingerprint. The database permits at most one winner per logical task
  and package fingerprint.
- All durable rows are tenant-keyed. PostgreSQL enables and forces RLS.

## Execution sequence

1. Synthesize packages from approved task specifications.
2. Persist packages and publish only ready package identities to
   `DatabaseQueue` on `factory.work`.
3. Claim the queue message and reload the package under its organization scope.
4. Allocate one or more candidates according to the package execution mode.
5. Create an exact-base worktree per execution/candidate.
6. Run bounded implementation, deterministic checks, and path validation.
7. Attest and publish each branch through `SideEffectCoordinator`.
8. Persist candidate delivery evidence and an optional governed winner
   selection.

Downgrade from revision `022` is deliberately refused while any factory table
contains rows; operators must archive or drain evidence explicitly.
