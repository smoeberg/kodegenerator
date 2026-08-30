# Fase 8 — Operations runbooks

These runbooks are the operational companion to the CI/CD boundary documented
in `DEPLOYMENT_AND_RELEASE.md`. They cover *drift operations*: on-/off-boarding
of machines, container & database security hardening, restore from backup,
vendor switches, staging usage, staging rollback to a known digest, and
reconciliation of unknown PR / image / deployment status.

Every runbook is written to be executed by an on-call operator, and to be
exercised at least once per quarter in a **fire drill** (see `FIRE_DRILL.md`).

---

## R-01: On-boarding a new machine

**Goal:** register a runner so it can build, test, and deploy DOR artifacts
without becoming a supply-chain risk.

1. Create the runner VM from the golden image (hardened base, no default
   credentials, SSH key-only access).
2. Install the runner agent as a systemd service with:
   - `User=runner`, no shell login, no password.
   - `ProtectSystem=strict`, `PrivateTmp=yes`, `NoNewPrivileges=yes`.
3. Add the machine to the GitHub runner group **and** to the DOR machine
   registry (the `infrastructure/machine_registry.json` equivalent used by
   swarm orchestration).
4. Grant the new runner only the repository scope it needs (build job token,
   never a personal access token).
5. Verify the runner can run `ci/verify_platform_skips.py` and one sandbox
   test (bwrap availability) before enabling it in the pool.
6. Record the on-boarding in the ops log: machine id, date, purpose, owner.

**Exit criteria:** the machine appears healthy in the runner pool and the
verify script passes.

---

## R-02: Off-boarding a machine

**Goal:** remove a machine quickly and provably, so it can never accept a
deployment or a secret after retirement.

1. Pause the runner out of the pool first (`gh api ... /pause` or UI).
   The machine must stop consuming work **before** credentials are revoked.
2. Revoke the runnner registration token and any SSH keys used for it.
3. Rotate any shared secrets the machine could have seen:
   - `DOR_JWT_SECRET_KEY`, DB password, encryption key: rotate via the
     documented key-rotation path (`docs/JWT_KEY_ROTATION.md`).
4. Terminate the VM, then verify it is gone from the pool and registry.
5. Reconcile the machine registry: remove the entry, record the off-boarding
   reason and timestamp in the ops log.

**Exit criteria:** the machine no longer appears in any pool, registry, or
DNS record, and its credentials are revoked.

---

## R-03: Docker container security hardening

**Goal:** ensure every container that DOR runs follows the same isolation
baseline as the phase-6 execution sandbox.

1. Build images with `--no-cache` from pinned base digests.
2. Run containers with:
   - `--read-only --tmpfs /tmp` (filesystem confinement)
   - `--cap-drop ALL` (no ambient capabilities)
   - `--security-opt no-new-privileges`
   - `--pids-limit 128` (resource limits)
   - `--network none` unless the container needs the network (network
     confinement)
3. Never run as root: use a non-root user in the image and
   `USER` in the Dockerfile.
4. Scan images with Trivy / Grype on every build; fail the pipeline on
   `CRITICAL` or `HIGH` findings (mirrors the `bandit` / `pip-audit` gates).
5. Verify with `reboot`-safe checks: `docker inspect` on every staging
   container shows read-only rootfs and dropped caps.

**Exit criteria:** a sample inspection of a running container confirms the
baseline, and the build pipeline has no unfixed high-severity findings.

---

## R-04: Database security hardening

**Goal:** keep the Postgres backing DOR (and its backups) private and
minimally privileged.

1. Postgres listens only on the internal network (never `0.0.0.0`), ideally
   a Unix socket; TLS required for every client connection.
2. Separate roles: `dor_app` (least privilege: CRUD on its schema),
   `dor_migrator` (owns migrations), `dor_readonly` (backups / analytics).
3. Enforce row-level security for tenant isolation (`TENANT_RLS.md`), and
   verify via `tests/infrastructure/test_tenant_rls.py` in CI.
4. Backups are encrypted at rest and in transit; encryption keys live in the
   secret store, never in the database or the repository.
5. Revoke access on off-boarding (R-02) and rotate credentials on any
   suspected leak; the JWT / encryption key rotation path covers the
   symmetric keys (`docs/JWT_KEY_ROTATION.md`).

**Exit criteria:** RLS test passes, no role has more than its documented
privileges, and backups are encrypted with keys in the secret store.

---

## R-05: Restore from backup

**Goal:** restore the data plane after data loss or corruption, with a
demonstrable restore drill.

1. Identify the backup to restore: pick the latest backup that predates the
   incident window (never a backup taken after the corruption).
2. Restore into a **fresh** database instance (never into the live one):
   - `pg_restore --clean --if-exists` on a staging/DR target.
3. Run the migration upgrade path backwards? No: **restore first, then
   apply the migrations that were pending at the backup point** so the
   restored schema matches the application version exactly.
4. Verify the restore: run the acceptance suite against the restored
   target (`make test-acceptance` with `DOR_DATABASE_URL` pointing at it).
5. Cut over: repoint the application connection, verify a smoke request,
   then record the restore in the ops log.

**Exit criteria:** acceptance passes on the restored target and a smoke
deploy works against it.

---

## R-06: Switch database vendor (provider change)

**Goal:** replace the Postgres provider (e.g. self-managed → managed,
or a new region) without losing durability.

1. Provision the new provider instance and verify connectivity from the
   integration runner.
2. Take a consistent logical backup (`pg_dump --format=custom`).
3. Restore into the new provider (R-05), keeping row-level security intact.
4. Freeze writes briefly, replay any delta, then switch the connection
   string in the deployment config (secret store).
5. Run the acceptance suite against the new provider, then decommission the
   old one per R-02.
6. Record the switch in the ops log with the migration timestamp.

**Exit criteria:** acceptance passes against the new provider and the old
instance is decommissioned.

---

## R-07: Switch artifact store (registry / object store)

**Goal:** move the container registry or artifact storage without breaking
deploy or release certification.

1. Provision the new store and mirror all current artifacts (digest-to-digest,
   preserving immutable digests).
2. Update the registry credentials in the secret store, not in code.
3. Update the deployment config so `DockerDeployService` points at the new
   store, keeping the old store readable for rollback.
4. Run the release executor test (`tests/pipeline/test_release_executor.py`)
   and the deploy executor test against the new store on the integration
   runner.
5. Verify a certification + rollback cycle through `reconcile_cli.py`.
6. Record the switch in the ops log.

**Exit criteria:** deployment and rollback work against the new store and
the old store is retained read-only for the retention window.

---

## R-08: Switch DNS provider

**Goal:** move the public DNS hosting without an outage window.

1. Export the full DNS zone from the current provider.
2. Import into the new provider and verify records 1:1 (A, CNAME, TXT,
   SPF, DKIM, DMARC).
3. Lower the TTL on critical records **before** the switch (at least 24 h
   ahead) so the cutover propagates quickly.
4. Switch the NS records at the registrar, then verify resolution from
   multiple vantage points.
5. Keep the old provider authoritative for one full TTL period; decommission
   after verification.

**Exit criteria:** resolution works from multiple vantage points after the
NS switch and the old provider is safe to decommission.

---

## R-09: Using staging

**Goal:** deploy anything to staging only through the certification gate.

1. Only certified digests may deploy to staging. A deploy to staging must
   reference a digest that exists in the certification ledger (see
   `ci/staging/ledger.json` produced by `reconcile_cli.py certify ...`).
2. Deploy with the deployment id recorded, so the deployment status is
   observable:
   `reconcile_cli.py certify --repo ... --image ... --digest sha256:... --gate-run <CI run id>`.
3. After deploy, run reconciliation:
   `reconcile_cli.py status --repo ... --image ... --digest <running>`.
4. If the status is anything but `OK`, do **not** leave staging in that
   state: roll back (R-10) or wait for certification (PENDING is a valid
   transient state only while the pipeline is still running).

**Exit criteria:** staging always runs either a certified digest or is
explicitly marked as being rolled back.

---

## R-10: Staging rollback to a known digest

**Goal:** bring staging back to a previously certified digest quickly.

1. Determine the rollback target:
   `reconcile_cli.py rollback --repo ... --image ... --ledger ci/staging/ledger.json`
   prints the latest **certified** digest for the image.
2. Deploy that digest to staging (same deploy path as R-09, but with the
   certified digest).
3. Reconcile: `reconcile_cli.py status ... --digest <target>` must report
   `OK`.
4. Record the rollback in the ops log: what was running, what it rolled back
   to, why, and who approved it.

**Exit criteria:** reconciliation reports `OK` for the rollback target and
the incident is recorded.

---

## R-11: Reconciliation of unknown PR / image / deployment status

**Goal:** when a PR, image, or deployment has no recorded status, classify it
deterministically instead of guessing.

1. Run:
   `reconcile_cli.py status --repo <repo> --image <image> --digest <observed> [--deployment-state deployed|pending]`.
2. Interpret the classification:
   - `OK` — observed digest is certified and matches expectation. Safe.
   - `PENDING` — status unknown, digest not certified; wait for the pipeline
     or roll back to a certified digest. **Do not leave staging in
     PENDING indefinitely.**
   - `DRIFT` — something moved staging without a certification event;
     investigate and roll back (R-10).
   - `ROLLBACK_REQUIRED` — an uncertified digest is deployed; roll back to
     the certified target immediately.
   - `MISMATCH` — a certified digest is running but it is not the expected
     one; decide whether the expected digest should become the target or the
     running digest must be rolled back.
3. Every reconciliation outcome must be written to the ops log (the CLI
   prints a JSON report that can be appended verbatim).

**Exit criteria:** every unknown-status deployment has a recorded
classification and an action.

---

## R-12: Deploy-failure fire drill

See `FIRE_DRILL.md`. The drill exercises:
1. Unknown deployment status → reconciliation (R-11).
2. Uncertified digest deployed → rollback to known digest (R-10).
3. Restore from backup on a fresh target (R-05).
4. Registry vendor switch with a retained old store (R-07).

The drill is green only when every step ends in `OK` or a recorded,
approved rollback.
