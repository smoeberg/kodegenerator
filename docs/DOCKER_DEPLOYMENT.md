# Docker deployment status

The only supported target for the canonical DOR demo is
`compose.demo.yml`. The architecture, container topology, and certification criteria are defined in
`docs/DEMO_INSTALLATION_CONTRACT.md` and
`ci/manifests/demo_installation_contract.json`.

## Current status

The Compose topology is **demo-certified**.
Queue wiring, authenticated worker identity, tenant-scope remediation, consolidated
startup validation, attested release gates, and the clean-room Docker certification test
suite (`scripts/run_demo_certification.py`) are fully verified in CI.

## Canonical runtime topology

```text
               +---------------------------------------------------+
               |                  compose.demo.yml                 |
               +---------------------------------------------------+
               |                                                   |
               |  postgres (5432)        minio (9000, 9001)        |
               |     ^                      ^                      |
               |     |                      |                      |
               |     +-- migrate (alembic) -+                      |
               |     |                      |                      |
               |     +-- api (8000) --------+                      |
               |     |                      |                      |
               |     +-- worker ------------+                      |
               |     |                      |                      |
               |     +-- dashboard (8501) --+                      |
               |                                                   |
               |  otel-collector (4317, 4318)                      |
               +---------------------------------------------------+
```

## Running the certified demo

```bash
# 1. Provide required environment variables
cp .env.demo.example .env.demo
# (fill out passwords/secrets in .env.demo)

# 2. Run clean-room runtime certification
python scripts/run_demo_certification.py --docker

# 3. Start demo containers
docker compose -f compose.demo.yml up --build -d
```
