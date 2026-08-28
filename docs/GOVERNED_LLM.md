# Governed LLM integration

Pipeline model calls are optional, structured proposal calls. They cannot write
files, execute commands, deploy an image, publish a PR, or grant authority. The
deterministic architecture, contract, test and verification backends remain the
source of truth.

## Configuration

Enable the proposal layer only when all values are configured:

```bash
export DOR_PIPELINE_LLM_ENABLED=true
export OPENAI_API_KEY='...'
export DOR_PIPELINE_LLM_MODEL='gpt-4.1-mini'
export DOR_PIPELINE_LLM_TIMEOUT_SECONDS=60
export DOR_PIPELINE_LLM_RETRIES=2
export DOR_PIPELINE_LLM_MAX_OUTPUT_TOKENS=2048
```

Every task must also supply `organization_id`, `actor_id`, a stable `task_id` or
`workflow_id`, and explicit input/output token budgets. Missing provider or model
configuration fails closed; the router no longer silently substitutes a mock.

## Request and result

```json
{
  "task_id": "task-42",
  "organization_id": "org-acme",
  "actor_id": "user-7",
  "llm_model": "gpt-4.1-mini",
  "llm_max_input_tokens": 8192,
  "llm_max_output_tokens": 1024,
  "requirements": ["GET /health returns 200"]
}
```

The stage output contains an advisory `llm_proposal` with its schema-validated
value and provenance: provider/model, provider request ID when available, input
and output fingerprints, token usage and replay status. Prompts and raw provider
envelopes are not included.

## Security and recovery

- Requirement and repository content is serialized beneath `untrusted_data` and
  cannot replace trusted instructions.
- Fields whose names indicate tokens, passwords, API keys, credentials or secrets
  are redacted before the provider call.
- Input budget is checked before network access. Output budget and JSON Schema are
  checked before a proposal is returned.
- Transient timeout, connection, HTTP 429 and HTTP 5xx errors use bounded adapter
  retries. Other failures and malformed output fail immediately.
- The idempotency key is bound to the prompt fingerprint. Repeating the same call
  returns the stored result without another provider call; rebinding it fails.

Use a stable external replay store before running multiple service processes.
The process-local ledger prevents duplicate calls within one worker; distributed
idempotency is completed with the persistence phase.
