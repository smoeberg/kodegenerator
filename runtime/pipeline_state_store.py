"""Lightweight persistence for pipeline orchestrator state.

Design goals:
  * Survive process restart without requiring the full WorkflowRepository yet
  * Atomic write (temp file + replace)
  * Serializable snapshot of workflows + domain tasks only (queue leases are
    ephemeral and are rebuilt as PENDING on load)

Swap this module for a DB-backed store later without changing orchestrator call sites.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value if hasattr(obj, "value") else obj.name
    if isinstance(obj, datetime):
        return obj.isoformat()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    if hasattr(obj, "to_dict") and callable(obj.to_dict):
        return obj.to_dict()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class PipelineStateStore:
    """File-backed snapshot store for pipeline workflows and tasks."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, snapshot: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(snapshot, default=_json_default, indent=2, sort_keys=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".pipeline-", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, self.path)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        logger.info("pipeline state saved path=%s workflows=%s", self.path, len(snapshot.get("workflows", {})))

    def load(self) -> Optional[dict[str, Any]]:
        if not self.path.exists():
            return None
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                logger.warning("pipeline state file is not an object: %s", self.path)
                return None
            return data
        except Exception:  # noqa: BLE001
            logger.exception("failed to load pipeline state from %s", self.path)
            return None

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()
