# Project Audit → Requirements & Plan

The Requirements & Plan page is the governed, non-executing continuation from Project Audit for `extend` and `modernize_rewrite` onboarding intents.

## Provenance boundary

Planning starts only when the authenticated Streamlit session contains both:

- the canonical onboarding intent returned by the governed onboarding API; and
- a Project Audit result bound to that exact intent and repository.

Before AI-6 is called, the adapter revalidates the canonical onboarding intent and requires the audit summary to match the same `intent_id`, purpose, repository, report, request fingerprint, manifest, evidence bundle, and commit. The audit must remain explicitly non-authoritative.

`audit_only` intents fail closed and cannot continue to requirements or planning.

## Human requirements

The user declares three bounded planning fields:

1. objective;
2. acceptance criteria; and
3. optional constraints.

Objective and acceptance criteria are required. Each field is bounded to 4,000 characters. The planning fingerprint is a SHA-256 over the exact audit provenance plus these human-declared requirements, so changing either upstream audit evidence or downstream requirements creates a different planning identity.

## AI-6 boundary

The bridge reuses the existing `phase4.planner.PlannerService` with its deterministic baseline provider. The generated plan is stored as `proposed`, `authoritative=false`, and `executable=false`.

Audit findings are included only as advisory review inputs. A Project Audit recommendation such as `CONTINUE`, `CONTINUE_WITH_GAPS`, `REPLAN`, or `ESCALATE` does not grant or remove execution authority. It is provenance for human planning judgment.

The page does not:

- create an execution command;
- invoke a worker;
- mutate the audited repository;
- create an authority decision;
- turn the AI-6 plan into executable work; or
- bypass the normal deterministic verification and authority gates.

A later slice may bridge an explicitly accepted plan into the existing governed command/execution boundary. That must remain a separate action with its own authority decision.
