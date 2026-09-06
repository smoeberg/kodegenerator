# Golden Real Run v1

## Purpose

Golden Real Run v1 is the first provider-backed, operator-reviewed delivery run over the Certified Demo Installation. It exercises the canonical delivery chain against `repository:demo/golden` and produces a local benchmark evidence report.

The run is intentionally separate from the legacy `/pipeline/start` state machine. `/pipeline/start` drives the older architecture/contracts/code/tests/deploy/release workflow, while the normative delivery chain in `docs/CANONICAL_SYSTEM_SPECIFICATION.md` is:

```text
Onboarding Intent
  -> Project Audit
  -> Requirements + AI-6 Plan
  -> Implementation Proposal
  -> Human Review
  -> Governed Patch Apply
  -> Delivery Verification Candidate
  -> Delivery Certificate
  -> Requirement Traceability
```

Golden Run v1 follows the latter chain. It does not treat a legacy pipeline `RELEASED` state as equivalent to Delivery Contract PASS, COMPLETE traceability, or semantic behavior verification.

## Fixed scenario

Organization:

```text
dor-demo-org
```

Repository:

```text
repository:demo/golden
```

Objective:

```text
Extend app.status() so the returned status document includes version 1.0.0 while preserving status ok.
```

Acceptance criterion:

```text
Calling app.status() returns exactly {"status": "ok", "version": "1.0.0"}.
```

The Implementation Agent scope is fixed to:

```text
app.py
```

with one-file / 20-changed-line budgets. The model cannot expand the run to `test_app.py`, dependencies, configuration, or unrelated files.

## Human review boundary

Golden Run is two-phase by design.

First:

```bash
make demo-golden-prepare
```

This command requires an already running Certified Demo Installation. It:

1. re-runs `demo-certify`;
2. authenticates as the generated demo administrator inside the dashboard container;
3. declares the immutable onboarding intent;
4. runs the governed read-only Project Audit against the audit checkout;
5. generates the non-executing deterministic AI-6 plan;
6. sends the bounded proposal request to the API, causing the **real configured Implementation Agent provider call**;
7. writes `.dor-demo/golden-run-prepared.json`;
8. prints the exact proposal id and unified diff;
9. stops with `classification=AWAITING_APPLY_APPROVAL`.

Nothing is applied during prepare.

After reviewing the exact diff, the operator must approve by naming the exact full proposal id:

```bash
make demo-golden-apply PROPOSAL_ID=<64-character-proposal-id>
```

A missing, stale, or different proposal id fails closed. There is no wildcard or `--yes` approval path.

## Governed apply and evidence chain

After exact proposal approval, `demo-golden-apply`:

1. reconstructs and revalidates onboarding -> audit -> plan -> proposal provenance;
2. submits the minimal governed patch apply command;
3. requires committed apply plus fixed lint/test/build evidence;
4. reconstructs the non-authoritative delivery candidate;
5. requests authoritative Delivery Contract v1 certification;
6. requires `result=pass`;
7. creates a structural Requirement -> Artifact traceability manifest;
8. requires `status=complete`;
9. runs the fixed Golden Run semantic benchmark oracle inside the API container;
10. writes `.dor-demo/golden-run-final.json` with a content-addressed `evidence_id`.

All generated run files stay in `.dor-demo/`, which is gitignored. No credentials or bearer tokens are included in run reports.

## Fixed semantic oracle

Delivery Certificate PASS proves the Delivery Contract v1 integrity/provenance contract; COMPLETE traceability proves structural reference coverage. Neither proves semantic requirement fulfillment.

Golden Run therefore adds one fixed benchmark-only oracle owned by this run contract. It imports only `/demo/patch-workspace/app.py` and requires:

```python
app.status() == {"status": "ok", "version": "1.0.0"}
```

It also requires the Git working-tree diff to contain exactly `app.py`.

The oracle cannot accept an arbitrary module, expression, expected value, path, command, or shell input from the operator. Its scope is fixed in repository code.

The oracle is **not** release, merge, deploy, production, or general semantic-verification authority. It exists only to make the benchmark's target behavior independently observable instead of trusting an agent-written test.

## Metrics

The final report records:

- `intent_to_verified_behavior_seconds` — wall clock from prepare start to the fixed semantic oracle observing the expected behavior;
- `intent_to_delivery_pass_seconds` — wall clock to Delivery Certificate PASS + COMPLETE traceability;
- `human_approval_wait_seconds` — time between proposal preparation and explicit apply approval;
- `provider_proposal_seconds` — wall time spent in the provider-backed Implementation Agent proposal request;
- `prepare_seconds`;
- `apply_certificate_traceability_seconds`.

This first observation is a benchmark datum, not evidence of a 2x improvement by itself. Comparative claims require multiple matched tasks and a baseline/control process.

## Authority boundaries

A `GOLDEN_RUN_PASS` means all of the following were observed for this fixed scenario:

- exact human-approved proposal id;
- successful governed patch apply;
- Delivery Certificate `pass`;
- Requirement Traceability `complete`;
- fixed benchmark oracle `ACCEPTED`.

It does **not** grant:

```json
{
  "release_authority": false,
  "merge_authority": false,
  "deploy_authority": false
}
```

The run does not perform release, merge, deployment, or production certification.

## Reset and replay

For a fresh timing observation, reset the demo first:

```bash
make demo-reset
make demo-up
make demo-certify
make demo-golden-prepare
```

Do not interpret an idempotent replay of an already-created proposal/apply/certificate as a fresh provider-backed timing observation.

## Evidence publication

The first real run is not considered repository evidence merely because the harness exists. After a local `GOLDEN_RUN_PASS`, the sanitized `.dor-demo/golden-run-final.json` must be reviewed and added to the PR under a repository evidence path before the milestone can be called complete from repository state.
