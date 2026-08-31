# Governed factory integration

Revision `023_factory_integration` adds the boundary that turns immutable
candidate deliveries into one attested integration result. It does not publish
a pull request. Final publication remains exclusively owned by
`GitPRPublisher.publish_patch_as_pr()` and requires a separate
`release.publish` grant.

## Invariants

- The integration plan is bound to one organization, repository, workflow,
  exact base SHA, ordered candidate commits, deterministic checks, and policy
  evidence.
- `factory.integrate` authority is mandatory and must bind the organization,
  repository, plan fingerprint, and exact base SHA.
- Candidate IDs are reloaded from tenant-scoped durable storage. Their package
  fingerprints, heads, bases, and ordered commits must still match the plan.
- The plan transitions through optimistic concurrency control. A stale worker
  cannot replace a newer integration result.
- The terminal mutation is fenced by `SideEffectCoordinator` using action
  `factory.integrate`; concurrent workers cannot run two integration suites or
  publish two integration branches.
- Integration uses a detached worktree at the exact base and cherry-picks only
  the ordered commit SHAs in the plan.
- A remote integration branch is created without force-push. An existing branch
  is accepted only when its head is identical.
- Conflicts are terminal, visible evidence. They do not publish a branch and do
  not produce a release handoff.
- A successful receipt requires a passing deterministic suite attestation and
  must match the completed durable side-effect result.
- The release handoff binds the exact base/head, patch content and fingerprint,
  integration receipt, branch, repository, and test attestation.
- Credentials and authority grants are never copied into plan or receipt rows.

## Crash and replay

The completed side-effect result is durable before the integration receipt and
terminal plan status are committed. After a crash, a worker may resume a
`running` plan: the side-effect coordinator replays the identical result, the
receipt append is idempotent, and OCC completes the plan. Once succeeded,
subsequent requests return the durable receipt and reconstruct the same release
handoff without rerunning the suite or pushing the branch.

Downgrade from revision `023` is refused until both integration tables are
explicitly archived or drained.
