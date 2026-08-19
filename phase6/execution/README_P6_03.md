# Phase 6 — Process Sandboxing (`BubblewrapProcessAdapter`)

Concrete isolation backend in `phase6/execution/process.py`.

## Environment requirement

Production process isolation requires **bubblewrap (`bwrap`)** on the host. CI
installs it via `sudo apt-get install -y bubblewrap` (see `.github/workflows/ci.yml`).
Local development without `bwrap` can still construct the adapter, validate
specs, and build isolation commands — only an actual process *launch* fails
closed.

## Fail-closed contract

`BubblewrapProcessAdapter` resolves `bwrap` **lazily at `execute()` time**, not
at construction. This keeps the security contract testable in any environment:

| Operation | Requires `bwrap`? |
|-----------|--------------------|
| `BubblewrapProcessAdapter(...)` construction | No |
| `execute(spec)` spec validation (allowlist, paths, network) | No — rejected first |
| `_build_command(spec)` command construction | No |
| Actual process launch (the `subprocess.Popen` call) | **Yes** — `ProcessSandboxUnavailable` if missing |

If `bwrap` is absent or not executable, `execute()` raises
`ProcessSandboxUnavailable` **before** any process is started. It never falls
back to an ordinary subprocess.

## Isolation properties

- **User / PID / UTS / IPC / network namespaces** via `--unshare-*`.
- **Read-only host filesystem** via `--ro-bind / /`; writable paths are explicit binds.
- **Executable allowlist**: `argv[0]` must resolve to an allowlisted absolute path.
- **Network deny**: `--unshare-net`; the backend rejects a `network_allowlist`
  (not yet supported — fail-closed rather than silently allowing).
- **Resource limits**: CPU, address space, process count, file size, open
  descriptors, core dumps (0), wall-clock time, and bounded output capture.
- **Bounded output**: captured to a file descriptor, not an unbounded pipe.
