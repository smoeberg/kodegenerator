# P3-19 — Distribution & Agent Routing Contract

## Purpose

P3-19 is the deterministic handoff boundary between the compiled Agent Contract Package and a specialist agent. Distribution does **not** invent work, rewrite prompts, choose architecture, or call an LLM.

## Inputs

- immutable `AgentContractPackage`
- package fingerprint
- approved task identity and fingerprint
- requested specialist role
- available input capabilities

## Routing rules

1. The package fingerprint supplied by the task must exactly match the package.
2. The requested role must resolve to exactly one compiled `AgentContract`.
3. Every required input declared by that contract must be available.
4. The selected contract's role, contract ID, fingerprint, inputs and permitted outputs are copied verbatim into the dispatch record.
5. No prompt rewriting or role substitution is permitted.
6. Missing or inconsistent evidence fails closed.
7. Dispatch identity is deterministic from task identity, task fingerprint, package fingerprint and selected contract fingerprint.

## Output

`DispatchRecord` contains:

- task identity and fingerprint
- package identity and fingerprint
- selected role
- contract identity and fingerprint
- required inputs
- permitted outputs
- deterministic dispatch fingerprint

## Security boundary

The distribution service is an enforcement point, not an autonomous planner. It can only route what P3-18 compiled. A downstream agent therefore receives the exact contract selected by the deterministic routing layer.

## Next gate

P3-20 consumes the resulting product and evidence package and independently determines whether it passes audit and test verification.
