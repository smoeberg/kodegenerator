"""FastAPI dependencies for the DOR runtime."""

from functools import lru_cache

from infrastructure.database.dor_runtime_db import DORRuntimeDB


@lru_cache(maxsize=1)
def get_dor() -> DORRuntimeDB:
    """Return the process-level DOR runtime."""
    return DORRuntimeDB()
