"""Filesystem policy primitives for the Phase 6 execution boundary."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from phase6.execution.sandbox import InvalidExecutionSpec


@dataclass(frozen=True)
class FilesystemPolicy:
    """Explicit host paths exposed to a sandbox.

    The default is deny-all: the policy only describes paths that the trusted
    runtime explicitly grants. Writable paths must not overlap read-only paths.
    """

    read_only_paths: tuple[str, ...] = ()
    writable_paths: tuple[str, ...] = ()

    def validate(self) -> None:
        readonly = {_canonical(path) for path in self.read_only_paths}
        writable = {_canonical(path) for path in self.writable_paths}
        if readonly & writable:
            raise InvalidExecutionSpec("filesystem path cannot be both read-only and writable")
        for path in (*readonly, *writable):
            if not os.path.isabs(path):
                raise InvalidExecutionSpec("sandbox filesystem paths must be absolute")
            if not os.path.exists(path):
                raise InvalidExecutionSpec(f"sandbox filesystem path does not exist: {path}")

    def as_mounts(self) -> tuple[tuple[str, str, bool], ...]:
        self.validate()
        return tuple((path, path, False) for path in self.read_only_paths) + tuple(
            (path, path, True) for path in self.writable_paths
        )


def _canonical(path: str) -> str:
    return str(Path(path).resolve())
