# Mandatory repository-first protocol

Read and follow [`AGENTS.md`](AGENTS.md) before analysing or changing this
repository. Conversation history and memory are not evidence of current state.

Run this preflight first:

```bash
git fetch origin --prune
python scripts/repository_state.py --base origin/main --validate
```

Stop with repository status `UNKNOWN` if fetch, source inspection, or state
validation cannot be completed.
