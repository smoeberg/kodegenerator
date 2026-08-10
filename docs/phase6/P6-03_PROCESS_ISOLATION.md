# Phase 6 — P6-03 Process Isolation

## Scope

P6-03 adds the first concrete execution isolation backend on top of the P6-02 sandbox contract.

The backend uses Linux `bubblewrap` (`bwrap`) to create a separate process environment with:

- PID namespace isolation;
- network namespace isolation (network denied by default);
- IPC and UTS namespace isolation;
- read-only host filesystem view;
- explicitly re-mounted writable paths only;
- isolated `/tmp`;
- explicit executable allowlisting;
- sanitized execution environment;
- CPU, address-space and process-count resource limits;
- wall-clock timeout;
- bounded output.

## Fail-closed rule

There is intentionally **no ordinary `subprocess` fallback**. If `bwrap` is not installed or executable, the adapter raises `ProcessSandboxUnavailable`.

This prevents a deployment from accidentally converting a security boundary into an unsandboxed host execution path.

## Network policy

P6-03 supports **network deny only**. A non-empty network allowlist is rejected because this backend does not yet provide a verified allowlist implementation.

Network allowlists belong to P6-05 and must not be approximated with application-level checks.

## Filesystem policy

The host root is exposed read-only. Explicit writable paths are re-bound read/write after the read-only root mount. Writable paths must already exist and must be absolute.

The adapter does not interpret arbitrary path strings as shell commands and does not invoke a shell.

## Executable policy

The adapter is constructed with a trusted executable allowlist. The first `argv` element must resolve to one of those paths. This prevents an execution request from selecting an arbitrary host executable merely because the sandbox backend is available.

## Resource policy

The trusted runtime supplies limits through `ExecutionLimits`. The adapter applies CPU, address-space and process limits to the sandbox launcher and enforces wall time and output size in the parent runtime.

The process-count limit is currently clamped to a minimum of two because the isolated launcher itself consumes one process while starting the sandboxed workload. P6-04 will replace this with a dedicated resource-control implementation where the configured workload count can be enforced independently.

## Verification

Unit tests cover:

- fail-closed behavior when `bwrap` is unavailable;
- executable allowlisting;
- network-deny semantics;
- namespace flags in the generated command;
- writable-path validation.

CI must validate the complete repository test and security suite before the PR is merged.

## Known limitation

`bubblewrap` is a Linux isolation primitive. P6-03 therefore does not claim equivalent isolation on non-Linux hosts. Production deployment requirements for the sandbox backend must be enforced before enabling this adapter in a runtime environment.
