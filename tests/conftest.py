"""Session-wide test environment defaults.

``api.auth`` seeds the bootstrap admin once at import time from
``DOR_ADMIN_USERNAME``/``DOR_ADMIN_PASSWORD``. Whichever test module imports
the API first therefore decides whether the admin exists, so local runs
without the CI workflow environment fail the swarm operations tests with 401
on ``/auth/token``. These defaults mirror the CI test-job environment
(``ci.yml``) and use ``setdefault`` so CI and explicit local settings win.
"""

from __future__ import annotations

import os

os.environ.setdefault("DOR_JWT_SECRET_KEY", "test-secret-key-min-32-chars-long")
os.environ.setdefault("DOR_ADMIN_USERNAME", "admin")
os.environ.setdefault("DOR_ADMIN_PASSWORD", "admin")
