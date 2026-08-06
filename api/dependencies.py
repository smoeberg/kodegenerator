"""FastAPI dependencies for the canonical DOR runtime."""

import os
from functools import lru_cache

from runtime.core import DORRuntime


@lru_cache(maxsize=1)
def get_dor() -> DORRuntime:
    """Return the process-level DOR runtime after applying Alembic migrations."""
    runtime = DORRuntime(os.getenv("DATABASE_URL", "sqlite:///./dor_runtime.db"))
    runtime.boot()
    return runtime
