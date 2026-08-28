# DOR Software Factory v1.0.0 Release Announcement

We are pleased to announce the official release of the **Digital Organization Runtime (DOR) Software Factory v1.0.0**.

## Highlights

- **Autonomous Software Factory Pipeline**: End-to-end orchestration from YAML requirements specification through architecture, contracts, code synthesis, automated test suites, and containerized deployment.
- **Fail-Closed Governance & Approval Gates**: Strict runtime enforcement, human-in-the-loop specialist gates, and deterministic state transitions.
- **Distributed Agent Swarm**: Resilient task queuing with worker heartbeat tracking, lease management, and claim-based execution.
- **Real Backend Executors**: Native executors for Architecture, Contracts, Code generation, Test execution, Deployment, and Git release operations.

## Quickstart

```bash
# Start the runtime
python -m runtime.main

# Launch swarm worker
python -m cli.worker --id worker-01 --caps code,test,domain,arch --pipeline
```
