# Pipeline requirements provenance and job records

Completion plan step 1 ([`docs/plan/FAERDIGGOERELSESPLAN.md`](plan/FAERDIGGOERELSESPLAN.md)):
every artifact carries the requirement ids and the requirements version it was
derived from, and every agent job gets a job record.

## Requirements revision

`domain/requirements_provenance.py` defines `RequirementsRef`:

| Field | Meaning |
|---|---|
| `revision` | 1 at pipeline start, +1 for every accepted change of content |
| `fingerprint` | SHA-256 of the canonical JSON of the spec (same encoding as `RequirementsSpecification.fingerprint`) |
| `declared_version` | The author's free-text `version`; informational only |
| `requirement_ids` | The declared ids in spec order; duplicates fail closed |

The orchestrator keeps the current reference in `workflow.context["requirements_ref"]`.
A change of content creates a new revision and appends the superseded reference to
`workflow.context["requirements_history"]`. Saving identical content keeps the revision.

## Stamping and staleness

Every task the orchestrator creates, including gate rework tasks, carries
`metadata["requirements_ref"]` for the revision current at creation.

On completion the orchestrator compares the task's reference with the current one.
A result built on a superseded revision is rejected: it is not merged into the
pipeline context, the state does not advance, the task is marked failed with
`stale requirements`, and its job record is closed as `rejected_stale`.

Accepted results are recorded in `workflow.context["artifact_provenance"][task_type]`
with the task id, the requirements reference, and the result keys.

Pipelines restored from snapshots written before this change have no reference.
Their current requirements are bound as revision 1 when the next task is created.
A workflow with no requirements spec at all gets tasks without a reference and a
logged warning; pipelines started through `/pipeline/start` always have one.

## Job records

`domain/agent_job.py` defines `AgentJobRecord`, one per task attempt:

- opened as `queued` when the task is created;
- `running` when a worker claims it through `PipelineAwareQueue` (worker id recorded);
- closed exactly once as `succeeded`, `failed`, or `rejected_stale`;
- a failed attempt that the queue will retry opens the next attempt.

Recorded per job: organization, workflow, task, task type, role, attempt,
requirements reference, agent identity (tool, worker, bot profile, provider, model,
model version), stack, prompt version, rule version, timestamps, duration, error,
usage, and measurements. Fields that are not known yet are `None`; the identity is
`dor-pipeline-executor` until the worker adapter (step 6) binds real coding agents.
Usage is taken from a `usage` mapping in the task result when present.

Measurements are limited to the keys in `MEASUREMENT_KEYS`, each written by the
control named in the completion plan. The record never derives them from an agent's
own report.

Job records are part of the pipeline snapshot (`"jobs"`) and are returned as `jobs`
in `GET /pipeline/{workflow_id}`.
