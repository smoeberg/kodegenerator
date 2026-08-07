# P3-16 — Deterministic Project Renderer

## Purpose

P3-16 closes the next boundary after the P3-15 architecture/scaffold contract:
turn a validated `ScaffoldPlan` into a canonical, immutable `RenderedProject`.

The renderer is deliberately **not** a filesystem writer and does not call an
LLM, Git, network service, or external process.

## Boundary

```text
ProjectDefinition
      |
      v
ScaffoldEngine
      |
      v
ScaffoldPlan
      |
      v
ProjectRenderer
      |
      v
RenderedProject
      |
      +--> canonical files
      +--> ordered manifest
      +--> deterministic fingerprint
      |
      v
P3-17 governed workspace writer
```

## Invariants

1. Only a valid `ScaffoldPlan` may be rendered.
2. Output paths are relative and cannot contain traversal segments.
3. Output paths are unique.
4. Files are emitted in canonical lexical path order.
5. Text line endings are normalized to LF.
6. Identical plans produce identical rendered files, manifest, and fingerprint.
7. Rendering does not mutate the input plan.
8. Rendering performs no filesystem, Git, network, subprocess, or LLM operation.
9. The renderer does not alter the architecture contract established by P3-15.

## Explicitly deferred

- writing files to a workspace;
- creating or modifying Git repositories;
- LLM-generated source;
- artifact/event persistence;
- additional architecture profiles.

Those capabilities must consume `RenderedProject` through separate governed
adapters in later phases.

## Acceptance gate

P3-16 is complete when CI proves deterministic output, canonical ordering,
line-ending normalization, invalid-plan rejection, duplicate-path rejection,
and non-mutation of the source `ScaffoldPlan`, together with the complete
existing repository test suite.
