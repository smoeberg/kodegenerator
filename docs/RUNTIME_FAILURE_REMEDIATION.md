# Governed runtime-failure remediation

`services.runtime_failure_remediation.RuntimeFailureRemediation` is the
provider-neutral application boundary for this sequence:

```text
runtime failure -> fingerprinted Redmine issue -> scoped WorkUnit -> claim
-> reproduction -> governed remediation -> independent review
-> exact-artifact verification -> release grant -> Draft PR
```

The service derives one stable lineage from organization, project, active-plan
fingerprint, repository, base SHA, and `FailureSignature.fingerprint`.
`api.dependencies.build_runtime_failure_remediation` binds the concrete Redmine,
project-scoped Work Queue, `GovernanceCoordinator`, verified-authority, ShipGate,
and Git PR adapters. The existing terminal-side-effect store fences the complete
pipeline and the Draft PR mutation. A durable approved-artifact checkpoint lets
a retry after verification failure resume at verification, grant, and Draft PR
publication without repeating issue creation, claim, reproduction, governance,
or review. Receipts are replayed only when every failure, issue, artifact,
verification, PR, and persisted `APPROVED` WorkUnit lineage field still matches.

The boundary grants no authority. Remediation is produced by the canonical
`GovernanceCoordinator`; its Coder provider in turn uses
`GovernedImplementationLifecycleExecutor` and `GovernedPatchExecutionRuntime`.
It requires a project-scoped claim with an
active lease, rejects remediation without reproduction evidence, requires the
reviewer provider to differ from the remediation provider, and accepts a Draft
PR only after the exact submitted artifact is approved, independently verified,
and named by a tenant/repository/base-bound release grant. Any missing or stale
binding fails closed before the next port is called.

The executable production boundary is:

```bash
python -m services.runtime_failure_remediation --failure runtime-failure.json
```

`DOR_RUNTIME_FAILURE_BINDINGS=module:callable` must name a configured dependency
factory whose mapping is passed to `build_runtime_failure_remediation`. The
factory wires existing providers and authority objects; it does not grant
authority. Missing or invalid configuration exits with a secret-free
`FAILED_CLOSED` result.
