"""TaskCompiler — transform a structured requirement into an execution context package.

Deterministic. No LLM calls. Produces prompt contracts for test and code
synthesizers plus atomic test specifications derived from acceptance criteria.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.context_engine import (
    ContextEngine,
    ContextPackage,
    SignatureRecord,
)


class TaskCompilerError(ValueError):
    """Raised when a requirement cannot be compiled safely."""
