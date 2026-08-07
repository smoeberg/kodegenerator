# P3-18 — Architecture & Agent Contract Compiler

## Purpose

P3-18 converts two **human-approved** source contracts into deterministic,
cryptographically bound contracts for specialist agents:

1. Requirements Contract
2. Architecture Contract

It does **not** ask an LLM to choose architecture, invent requirements,
write files, or dispatch work.

## Pipeline

```text
Human functional wishes
        |
        v
Requirements Contract ---- human approval ----+
                                             |
Architecture proposal ---- human approval ---+--> Contract Compiler
                                                   |
                                                   +--> Development Agent
                                                   +--> Test Agent
                                                   +--> Audit Agent
                                                   +--> Security Agent
                                                   +--> Documentation Agent
                                                   +--> Project Management Agent
                                                   +--> Distribution Agent
```

## Hard gates

Compilation is rejected unless:

- requirements status is `approved`;
- requirements approval status is `approved`;
- requirements approval fingerprint equals the requirements content fingerprint;
- requirements validation has no blocking issues;
- architecture status is `approved`;
- architecture has explicit human approval identity and timestamp.

## Determinism

Every agent contract contains:

- source requirements fingerprint;
- source architecture fingerprint;
- stable agent role;
- explicit required inputs;
- explicit permitted outputs;
- explicit forbidden actions;
- acceptance-criteria identifiers;
- deterministic instructions;
- a contract fingerprint.

The generated `system_prompt` is a rendering of that contract. It is not an
LLM-generated prompt.

## Distribution boundary

The distribution agent is deliberately constrained to selecting from compiled
agent contracts. It cannot rewrite prompts, invent a role, or bypass evidence
gates. Actual queueing/dispatch and specialist execution are subsequent phases.

## Architectural rule

**AI proposes. Human approves. Compiler binds. Specialist agents execute.
Independent audit/test decides whether the result is acceptable.**
