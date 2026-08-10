# P6-03 status

Implementation is on `phase6/p6-03-process-isolation`.

The concrete backend is `BubblewrapProcessAdapter`. It fails closed without `bwrap`, denies network access through a Linux network namespace, exposes the host filesystem read-only, permits only explicitly writable paths, requires an executable allowlist, applies process resource limits, enforces wall-clock timeout, and bounds output.

CI is the acceptance gate before merge.