"""Small worker-loop utility with graceful shutdown semantics."""
from __future__ import annotations

import time
from typing import Callable


class WorkerLoop:
    def __init__(self, run_once: Callable[[], object | None], poll_seconds: float = 1.0):
        if poll_seconds < 0:
            raise ValueError("poll_seconds must be non-negative")
        self.run_once = run_once
        self.poll_seconds = poll_seconds
        self._stopping = False

    def stop(self) -> None:
        self._stopping = True

    def run(self, max_iterations: int | None = None) -> int:
        iterations = 0
        while not self._stopping and (max_iterations is None or iterations < max_iterations):
            result = self.run_once()
            iterations += 1
            if result is None and self.poll_seconds:
                time.sleep(self.poll_seconds)
        return iterations
