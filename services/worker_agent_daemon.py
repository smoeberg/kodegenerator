"""Autonomous worker agent daemon for the DOR swarm task queue.

A WorkerAgent is the long-running process that represents one AI bot in the
field: it claims eligible tasks, keeps the lease alive with heartbeats,
invokes a patch synthesizer, and reports completion or failure.
"""

from __future__ import annotations

import logging
import signal
import threading
from collections.abc import Callable, Sequence
from dataclasses import asdict, is_dataclass
from typing import Any, Protocol

from services.swarm_task_queue import QueuedTask, SwarmTaskQueue

logger = logging.getLogger(__name__)


class TaskSynthesizer(Protocol):
    """Minimal interface the daemon needs from a code/patch synthesizer."""

    def synthesize(self, task: QueuedTask) -> Any:
        """Produce a patch_result for the claimed task.

        May raise any exception; the daemon treats that as task failure.
        """
        ...


def _default_synthesizer(task: QueuedTask) -> dict[str, Any]:
    """Placeholder synthesizer used when none is injected (dev/tests)."""
    return {
        "task_id": task.task_id,
        "name": task.name,
        "artifact": f"{task.task_id}.py",
        "lines": 0,
        "status": "noop",
    }


def _serialise_patch_result(result: Any) -> Any:
    if result is None:
        return {}
    if is_dataclass(result) and not isinstance(result, type):
        try:
            return asdict(result)
        except Exception:  # noqa: BLE001
            return {"repr": repr(result)}
    if hasattr(result, "to_dict") and callable(result.to_dict):
        return result.to_dict()
    return result


class WorkerAgent:
    """Claim → heartbeat → synthesize → complete/fail loop for one worker.

    Parameters
    ----------
    worker_id:
        Stable agent identity used for claim ownership and heartbeats.
    capabilities:
        Capability tokens this worker is allowed to claim
        (e.g. ``cap.code.generation``).
    queue:
        Shared :class:`SwarmTaskQueue` instance.
    synthesizer:
        Object or callable that turns a :class:`QueuedTask` into a
        ``patch_result``. Defaults to a no-op synthesizer.
    poll_interval:
        Seconds to sleep when the queue has no eligible work.
    heartbeat_interval:
        Seconds between heartbeat calls while a task is in progress.
        Must be comfortably below the queue lease TTL.
    max_idle_cycles:
        Optional stop condition for tests: exit after this many consecutive
        empty claim cycles. ``None`` means run until stop is requested.
    """

    def __init__(
        self,
        worker_id: str,
        capabilities: Sequence[str],
        queue: SwarmTaskQueue,
        synthesizer: Any = None,
        *,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 30.0,
        max_idle_cycles: int | None = None,
        identity_verifier: Callable[[], str] | None = None,
    ) -> None:
        if not worker_id or not str(worker_id).strip():
            raise ValueError("worker_id is required")
        caps = [str(c).strip() for c in capabilities if str(c).strip()]
        if not caps:
            raise ValueError("capabilities must not be empty")

        self.worker_id = str(worker_id).strip()
        self.capabilities = list(caps)
        self.queue = queue
        self.poll_interval = max(0.0, float(poll_interval))
        self.heartbeat_interval = max(0.1, float(heartbeat_interval))
        self.max_idle_cycles = max_idle_cycles
        self._identity_verifier = identity_verifier

        if synthesizer is None:
            self._synthesize: Callable[[QueuedTask], Any] = _default_synthesizer
        elif callable(synthesizer) and not hasattr(synthesizer, "synthesize"):
            self._synthesize = synthesizer  # type: ignore[assignment]
        else:
            self._synthesize = synthesizer.synthesize  # type: ignore[assignment]

        self._stop = threading.Event()
        self._current_task: QueuedTask | None = None
        self._lock = threading.RLock()
        self._idle_cycles = 0
        self._completed = 0
        self._failed = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def request_stop(self) -> None:
        """Signal the run loop to exit after the current unit of work."""
        logger.info("worker=%s stop requested", self.worker_id)
        self._stop.set()

    @property
    def is_running(self) -> bool:
        return not self._stop.is_set()

    @property
    def current_task_id(self) -> str | None:
        with self._lock:
            return self._current_task.task_id if self._current_task else None

    def run(self, *, install_signal_handlers: bool = False) -> None:
        """Main claim / execute loop. Blocks until stop is requested."""
        if install_signal_handlers:
            self._install_signal_handlers()

        logger.info(
            "worker=%s starting capabilities=%s poll=%.2fs heartbeat=%.2fs",
            self.worker_id,
            self.capabilities,
            self.poll_interval,
            self.heartbeat_interval,
        )

        try:
            while not self._stop.is_set():
                claimed = self._claim_once()
                if claimed is None:
                    self._idle_cycles += 1
                    if (
                        self.max_idle_cycles is not None
                        and self._idle_cycles >= self.max_idle_cycles
                    ):
                        logger.info(
                            "worker=%s max idle cycles reached (%s); stopping",
                            self.worker_id,
                            self.max_idle_cycles,
                        )
                        break
                    if self.poll_interval > 0:
                        self._stop.wait(self.poll_interval)
                    continue

                self._idle_cycles = 0
                self._execute_claimed(claimed)
        finally:
            self._release_current_on_shutdown()
            logger.info(
                "worker=%s stopped completed=%s failed=%s",
                self.worker_id,
                self._completed,
                self._failed,
            )

    def run_once(self) -> QueuedTask | None:
        """Claim and process at most one task (useful for tests)."""
        claimed = self._claim_once()
        if claimed is None:
            return None
        self._execute_claimed(claimed)
        return claimed

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _claim_once(self) -> QueuedTask | None:
        try:
            self._verify_identity()
            task = self.queue.claim_next_task(self.worker_id, self.capabilities)
        except Exception:
            logger.exception("worker=%s claim failed", self.worker_id)
            return None
        if task is None:
            return None
        with self._lock:
            self._current_task = task
        logger.info(
            "worker=%s transition=CLAIMED task_id=%s name=%s capabilities=%s",
            self.worker_id,
            task.task_id,
            task.name,
            list(task.capabilities),
        )
        return task

    def _execute_claimed(self, task: QueuedTask) -> None:
        stop_heartbeat = threading.Event()
        hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(task.task_id, stop_heartbeat),
            name=f"heartbeat-{self.worker_id}-{task.task_id}",
            daemon=True,
        )
        hb_thread.start()
        try:
            try:
                raw_result = self._synthesize(task)
                patch_result = _serialise_patch_result(raw_result)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "worker=%s transition=FAILED task_id=%s error=%s",
                    self.worker_id,
                    task.task_id,
                    error,
                )
                self._safe_fail(task.task_id, error, retry=True)
                self._failed += 1
                return

            try:
                self._verify_identity()
                self.queue.complete_task(task.task_id, self.worker_id, patch_result)
                logger.info(
                    "worker=%s transition=COMPLETED task_id=%s patch_keys=%s",
                    self.worker_id,
                    task.task_id,
                    list(patch_result)
                    if isinstance(patch_result, dict)
                    else type(patch_result).__name__,
                )
                self._completed += 1
            except Exception as exc:
                error = f"complete_task failed: {type(exc).__name__}: {exc}"
                logger.exception(
                    "worker=%s transition=FAILED task_id=%s error=%s",
                    self.worker_id,
                    task.task_id,
                    error,
                )
                self._safe_fail(task.task_id, error, retry=True)
                self._failed += 1
        finally:
            stop_heartbeat.set()
            hb_thread.join(timeout=self.heartbeat_interval + 1.0)
            with self._lock:
                if self._current_task and self._current_task.task_id == task.task_id:
                    self._current_task = None

    def _heartbeat_loop(self, task_id: str, stop: threading.Event) -> None:
        while not stop.wait(self.heartbeat_interval):
            try:
                self._verify_identity()
                self.queue.heartbeat(task_id, self.worker_id)
                logger.info(
                    "worker=%s transition=HEARTBEAT task_id=%s",
                    self.worker_id,
                    task_id,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "worker=%s heartbeat failed task_id=%s error=%s",
                    self.worker_id,
                    task_id,
                    exc,
                )
                # Lease may have been reclaimed; stop hammering the queue.
                return

    def _safe_fail(self, task_id: str, error: str, *, retry: bool) -> None:
        try:
            self._verify_identity()
            self.queue.fail_task(task_id, self.worker_id, error, retry=retry)
        except Exception:
            logger.exception(
                "worker=%s fail_task also failed task_id=%s",
                self.worker_id,
                task_id,
            )

    def _verify_identity(self) -> None:
        if self._identity_verifier is None:
            return
        if self._identity_verifier() != self.worker_id:
            raise PermissionError("worker service identity binding changed")

    def _release_current_on_shutdown(self) -> None:
        with self._lock:
            task = self._current_task
            self._current_task = None
        if task is None:
            return
        logger.info(
            "worker=%s releasing task_id=%s on shutdown",
            self.worker_id,
            task.task_id,
        )
        self._safe_fail(
            task.task_id,
            "worker shutdown before completion",
            retry=True,
        )

    def _install_signal_handlers(self) -> None:
        def _handler(signum, _frame):
            logger.info(
                "worker=%s received signal %s; requesting stop",
                self.worker_id,
                signum,
            )
            self.request_stop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                # Not the main thread or signals unavailable (e.g. under some
                # test runners) — ignore.
                logger.debug(
                    "worker=%s could not install handler for %s",
                    self.worker_id,
                    sig,
                )
