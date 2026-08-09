# Phase 4B — Control Plane Core API v1

**Status:** Operational Slice 1 contract

**Contract version:** `1.0`

**API prefix:** `/api/v1/control-plane`

## Purpose

This contract defines the first governed write path used by DOR's first-party
Control Plane. It captures an immutable project intent and records a launch
request without granting the GUI, caller, or an agent execution or verification
authority.

```text
Control Plane command
  -> authenticated API v1 request
  -> organization context
  -> persisted capability resolution
  -> validated project transition
  -> atomic project, command receipt, and audit persistence
  -> versioned project and event response
```

## Commands

| Method and path | Capability | State transition | Success |
| --- | --- | --- | --- |
| `POST /api/v1/control-plane/projects` | `project.create` | none -> `created` | `201` |
| `POST /api/v1/control-plane/projects/{project_id}/launch` | `project.launch` | `created` -> `launch_requested` | `202` |

Every command requires `contract_version: "1.0"`, an exact
`organization_id`, and a caller-supplied `command_id`. The durable command
receipt binds the ID to the organization, actor, command type, and canonical
payload. Replaying the same command returns the stored project without emitting
new events. Rebinding the ID fails with `409`.

Project IDs are deterministically derived from the organization and create
command ID. Launch requires the exact immutable `project_fingerprint` returned
by the create response. This prevents a stale or substituted project snapshot
from being launched.

## Queries and event contract

| Method and path | Capability | Result |
| --- | --- | --- |
| `GET /api/v1/control-plane/projects/{project_id}` | `project.read` | Current organization-scoped snapshot |
| `GET /api/v1/control-plane/projects/{project_id}/events` | `project.read` | Cursor-bounded append-only event envelopes |

The event query supports `after_sequence`, `limit` (maximum 100), and
`include_authorization_audit`. Each response event includes its contract
version, per-project sequence, correlation ID, metadata, and a SHA-256 envelope
fingerprint. The same envelope is the normative payload for a future
authenticated WebSocket stream; this slice does not expose a WebSocket yet.

The project stream contains:

- `AUTHORIZATION_GRANTED` or `AUTHORIZATION_DENIED` for write commands;
- `PROJECT_CREATED` after atomic intent persistence;
- `PROJECT_LAUNCH_REQUESTED` after the fingerprint-bound launch transition.

There is no API that updates or deletes historical events, intent snapshots, or
fingerprints.

## Governance boundary

`launch_requested` means that DOR accepted a governed request to begin the
project pipeline. It does **not** mean that execution started, requirements or
architecture were approved, tests passed, or P3-20 returned `PASS`.

Later slices must consume the launch request through PM planning, Context
Packets, authorized execution, Test and Audit evidence, and P3-20 independent
verification. They must link their records to the project and launch
fingerprints defined here. No caller or agent may replace that chain with a
self-declared success state.
