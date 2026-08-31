# Multi-bot factory E2E acceptance

`tests/e2e/test_multi_bot_factory_contract.py` is the executable acceptance
boundary for MBF-09 through MBF-14. It uses real SQLAlchemy stores, queue
leases, execution fencing tokens, side-effect receipts, temporary Git
repositories, worktrees, commits, and remote branches. Only model/provider and
GitHub API behavior is hermetic.

| Contract | Executable proof |
| --- | --- |
| MBF-09 | Twenty simultaneous workers claim twenty distinct messages, create isolated exact-base worktrees, modify non-overlapping scopes, publish twenty unique branches, and persist twenty deliveries. |
| MBF-10 | An expired queue lease and execution claim are reclaimed; the old lease ID and fencing token cannot acknowledge or complete. |
| MBF-11 | Three real competing commits are persisted, but concurrent selection transactions commit exactly one winner. |
| MBF-12 | A crash after remote push but before receipt completion leaves one branch; lease recovery reconciles the identical head without another branch mutation. |
| MBF-13 | A changed base SHA invalidates both the original authority binding and the candidate evidence under a newly bound grant. |
| MBF-14 | Twenty integration attempts execute one suite and create one durable receipt; twenty release attempts under a distinct verified grant create one hermetic PR operation and replay one result. |

The suite also guards two defects discovered while constructing the proof:

- `DatabaseQueue.claim()` now uses database compare-and-set rather than relying
  on `FOR UPDATE`, which SQLite ignores.
- `FactoryCandidateSelectionModel` declares the same partial unique-winner
  index as migration `022`, so `Base.metadata.create_all()` and migrated
  databases enforce identical semantics.

Importing `execution.factory_task_synthesizer` no longer initializes unrelated
deploy, HTTP, and release adapters. `execution.__init__` retains its public
compatibility exports through lazy module attributes.
