"""Immutable agent log (completion plan, decision 37).

Every agent job keeps its log: prompt, context packet, the agent's full
machine-readable stream, the diff and test output. The log is DOR's own
record; the providers' retention is not relied upon. Entries are
content-addressed (``sha256:<hex>``): the same content always gets the same
reference, an entry is never overwritten, and reading verifies the content
against its reference.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


class AgentLogError(RuntimeError):
    """An agent log entry is missing, tampered with or cannot be written."""


def _encode(entry: Mapping[str, Any]) -> bytes:
    return json.dumps(
        entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


class FileAgentLogStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @classmethod
    def from_environment(cls) -> FileAgentLogStore:
        return cls(os.getenv("DOR_AGENT_LOG_DIR", "./var/agent-logs"))

    def _path(self, digest: str) -> Path:
        return self._root / digest[:2] / f"{digest}.json"

    def put(self, entry: Mapping[str, Any]) -> str:
        data = _encode(entry)
        digest = hashlib.sha256(data).hexdigest()
        path = self._path(digest)
        if path.exists():
            if path.read_bytes() != data:
                raise AgentLogError(f"agent log {digest} exists with different content")
            return f"sha256:{digest}"
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
            os.chmod(temporary, 0o444)
            # Atomic and never replaces an existing entry.
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise AgentLogError(
                    f"agent log {digest} exists with different content"
                ) from None
        finally:
            Path(temporary).unlink(missing_ok=True)
        return f"sha256:{digest}"

    def get(self, reference: str) -> dict[str, Any]:
        if not reference.startswith("sha256:"):
            raise AgentLogError(f"invalid agent log reference {reference!r}")
        digest = reference.split(":", 1)[1]
        path = self._path(digest)
        try:
            data = path.read_bytes()
        except FileNotFoundError as exc:
            raise AgentLogError(f"agent log {reference} not found") from exc
        if hashlib.sha256(data).hexdigest() != digest:
            raise AgentLogError(f"agent log {reference} does not match its reference")
        return json.loads(data)
