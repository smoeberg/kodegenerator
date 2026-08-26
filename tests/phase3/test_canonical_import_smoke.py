"""Import every supported process entrypoint in isolated interpreters."""

import os
import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module_name",
    (
        "api.main",
        "main",
        "cli.main",
        "services.api",
        "services.worker_agent",
        "phase4.project_audit.runtime",
    ),
)
def test_canonical_entrypoint_imports_cleanly(module_name: str) -> None:
    env = os.environ.copy()
    env.update(
        {
            "DOR_ENV": "test",
            "DOR_JWT_SECRET_KEY": "canonical-import-test-secret",
            "DOR_ADMIN_PASSWORD": "canonical-import-admin-password",
            "PYTHONPATH": ".",
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
