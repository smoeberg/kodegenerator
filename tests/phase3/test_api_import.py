"""Phase 3 API boot-boundary smoke test."""
import os
import subprocess
import sys


def test_api_main_imports_cleanly() -> None:
    env = os.environ.copy()
    env["DOR_JWT_SECRET_KEY"] = "ci-only-test-secret"
    env["PYTHONPATH"] = "."
    result = subprocess.run(
        [sys.executable, "-c", "from api.main import app; assert app.title.startswith('Digital Organization Runtime')"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
