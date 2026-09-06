# DOR golden demo repository

This intentionally tiny Python repository is the deterministic input for the certified demo installation and the later Golden Run.

Baseline behavior: `app.status()` returns `{"status": "ok"}` and `test_app.py` verifies that behavior.

The seed command creates two distinct Git checkouts from this fixture:

- a read-only Project Audit checkout mounted only into the dashboard;
- a governed writable patch workspace mounted only into the API.

Both checkouts start at the exact same deterministic Git commit.
