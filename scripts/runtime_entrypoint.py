"""Container entrypoint with file-backed production secret loading."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from collections.abc import Sequence

from services.runtime_configuration import validate_runtime_configuration
from services.runtime_secrets import materialize_runtime_secrets


def _enabled(name: str) -> bool:
    return os.environ.get(name, "0") == "1"


def _run_module(*arguments: str) -> None:
    subprocess.run([sys.executable, "-m", *arguments], check=True)


def main(argv: Sequence[str] | None = None) -> None:
    command = list(sys.argv[1:] if argv is None else argv)
    if not command:
        raise RuntimeError("runtime entrypoint requires a command")

    materialize_runtime_secrets()

    run_migrations = _enabled("DOR_RUN_MIGRATIONS")
    if run_migrations:
        _run_module("scripts.init_database")

    validate_runtime_configuration()

    if run_migrations:
        if not Path("/app/alembic.ini").is_file() or not Path("/app/alembic").is_dir():
            raise RuntimeError("migration configuration is missing")
        _run_module("alembic", "upgrade", "head")

    if _enabled("DOR_BOOTSTRAP_ARTIFACT_BUCKET"):
        _run_module("scripts.bootstrap_artifact_store")
    if _enabled("DOR_BOOTSTRAP_WORKER_IDENTITY"):
        _run_module("scripts.bootstrap_worker_identity")

    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
