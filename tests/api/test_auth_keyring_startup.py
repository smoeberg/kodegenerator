from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_production_auth_import_accepts_named_keyring_without_legacy_secret() -> None:
    environment = os.environ.copy()
    environment.update(
        {
            "DOR_ENV": "production",
            "DOR_ADMIN_USERNAME": "admin",
            "DOR_ADMIN_PASSWORD": "a" * 32,
            "DOR_ADMIN_ORGANIZATION_ID": "org-1",
            "DOR_JWT_SIGNING_KEYS": json.dumps({"2026-09": "j" * 32}),
            "DOR_JWT_ACTIVE_KEY_ID": "2026-09",
        }
    )
    environment.pop("DOR_JWT_SECRET_KEY", None)
    environment.pop("DATABASE_URL", None)
    environment.pop("DOR_IDENTITY_DATABASE_URL", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import api.auth; "
            "from services.jwt_keyring import JWTKeyRing; "
            "assert JWTKeyRing.from_environment(production=True).active_key_id == '2026-09'",
        ],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
