# P3-15 — Project Architecture & Scaffold Contract

## Purpose

P3-15 turns `kodegenerator` from a workflow/governance runtime into a system that can **define and validate the architecture of a generated software project**.

The first implementation is intentionally narrow: Python + FastAPI + PostgreSQL using a hexagonal architecture. The contract is designed so additional profiles can be added without weakening existing invariants.

## Boundary

```text
ProjectDefinition
      |
      v
Architecture Profile
      |
      v
Deterministic ScaffoldPlan
      |
      +--> files
      +--> architecture contract
      +--> fingerprint
      |
      v
Architecture Validation
```

The engine produces a plan. It does not write files, execute generated code, call an LLM, or mutate a target repository.

## Invariants

1. Project definitions are strict (`extra=forbid`).
2. Project names are safe relative paths / package identifiers.
3. Unsupported language, API, database, or architecture choices fail closed.
4. A scaffold is deterministic: identical definitions produce identical files and fingerprint.
5. Every generated path is relative and cannot contain `..` traversal.
6. The architecture contract is explicit and validated before a plan is returned.
7. LLM output is not trusted as the architecture source of truth.
8. Disk writes and repository mutations are outside this phase and require a later governed adapter.

## First supported profile

`hexagonal / python / fastapi / postgresql`

Required boundaries:

- `src/domain/`
- `src/application/`
- `src/ports/`
- `src/adapters/`
- `tests/`

The domain and application layers are intentionally framework-independent. Transport and infrastructure concerns belong in adapters.

## P3-15 acceptance gate

The phase is not complete until CI proves:

- project-definition validation tests pass;
- deterministic scaffold tests pass;
- path-safety tests pass;
- architecture contract validation passes;
- existing repository tests remain green;
- no generated scaffold writes to the DOR repository itself.

## Explicitly deferred

- Jinja/Handlebars templating;
- arbitrary LLM-generated source files;
- direct filesystem writes;
- Git commits/branches in generated projects;
- additional architecture profiles;
- artifact/event persistence integration.

Those are subsequent capabilities and must consume this contract rather than bypass it.
