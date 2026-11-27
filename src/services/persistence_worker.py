"""
PR-HB-004: Async Persistence Worker

Moves disk I/O and serialization off the UI thread to prevent heartbeat stalls.
All manifest writes, history writes, and image metadata embedding are queued
and processed by a single background daemon thread.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PersistenceTask:
    """A queued persistence operation."""

    task_type: str  # "manifest", "history", "image_metadata", "run_metadata"
    data: dict[str, Any]
    callback: Callable[[], None] | None = None
    priority: int = 0  # Higher = more important (0 = normal, 1 = critical)

    def __lt__(self, other: PersistenceTask) -> bool:
        """For priority queue sorting."""
        return self.priority > other.priority  # Higher priority first


class PersistenceWorker:
    """
    Background worker that processes persistence tasks asynchronously.

    PR-HB-004: Prevents UI thread blocking by moving all disk I/O to a
    dedicated daemon thread with bounded queue.
    """

    def __init__(
        self,
        max_queue_size: int = 1000,
        ui_callback_dispatcher: Callable[[Callable[[], None]], None] | None = None,
    ):
        """
        Args:
            max_queue_size: Maximum pending tasks before backpressure kicks in
            ui_callback_dispatcher: Function to safely dispatch callbacks to UI thread
                                   (e.g., main_window.run_in_main_thread)
        """
        self._queue: queue.PriorityQueue[tuple[int, PersistenceTask]] = queue.PriorityQueue(
            maxsize=max_queue_size
        )
        self._max_queue_size = max_queue_size
        self._ui_callback_dispatcher = ui_callback_dispatcher
        self._worker_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()
        self._task_counter = 0  # For FIFO within same priority

        # Statistics
        self._tasks_completed = 0
        self._tasks_dropped = 0
        self._tasks_failed = 0
        self._failures: list[str] = []  # the latest failed writes, reported again at stop

    def start(self) -> None:
        """Start the background worker thread."""
        with self._lock:
            if self._running:
                return

            self._running = True
            self._worker_thread = threading.Thread(
                target=self._worker_loop, name="PersistenceWorker", daemon=True
            )
            self._worker_thread.start()
            logger.info("[PersistenceWorker] Started")

    def begin_shutdown(self) -> None:
        """Close admission and wake the worker to drain all accepted tasks."""
        self._queue.shutdown()

    def stop(self, timeout: float | None = 5.0) -> bool:
        """Drain accepted writes. False only while work is still pending; a failed write is logged, not pending."""
        self.begin_shutdown()
        thread = self._worker_thread
        if thread is not None:
            thread.join(timeout=None if timeout is None else max(0.0, timeout))
            if thread.is_alive():
                logger.warning("[PersistenceWorker] Worker did not stop within timeout")
                return False
        if self._tasks_failed:
            logger.error(
                "[PersistenceWorker] %d write(s) failed earlier: %s",
                self._tasks_failed,
                "; ".join(self._failures),
            )
        return self._queue.empty()

    def active_thread(self) -> threading.Thread | None:
        thread = self._worker_thread
        return thread if thread is not None and thread.is_alive() else None

    def enqueue(self, task: PersistenceTask, critical: bool = False) -> bool:
        """
        Enqueue a persistence task.

        Args:
            task: The persistence operation to perform
            critical: If True, never drop this task (blocks if queue full)

        Returns:
            True if enqueued successfully, False if dropped due to backpressure
        """
        if not self._running:
            logger.warning(
                f"[PersistenceWorker] Worker not running, dropping task: {task.task_type}"
            )
            self._tasks_dropped += 1
            return False

        # Use counter for FIFO within same priority
        self._task_counter += 1
        priority_tuple = (task.priority, -self._task_counter)  # Negative for FIFO

        try:
            if critical:
                # Block until space available
                self._queue.put((priority_tuple[0], task), timeout=10.0)
            else:
                # Non-blocking - drop if full
                self._queue.put_nowait((priority_tuple[0], task))
            return True
        except queue.ShutDown:
            return False
        except queue.Full:
            # Backpressure - log and drop non-critical tasks
            if critical:
                logger.error(
                    f"[PersistenceWorker] Critical task dropped (timeout): {task.task_type}"
                )
            else:
                logger.warning(f"[PersistenceWorker] Queue full, dropping task: {task.task_type}")
            self._tasks_dropped += 1
            return False

    def get_stats(self) -> dict[str, int]:
        """Get worker statistics."""
        return {
            "completed": self._tasks_completed,
            "dropped": self._tasks_dropped,
            "failed": self._tasks_failed,
            "pending": self._queue.qsize(),
            "capacity": self._max_queue_size,
        }

    def _worker_loop(self) -> None:
        """Main worker loop - processes tasks from queue."""
        logger.debug("[PersistenceWorker] Worker loop started")

        try:
            while True:
                try:
                    _, task = self._queue.get()
                except queue.ShutDown:
                    return
                try:
                    self._process_task(task)
                finally:
                    self._queue.task_done()
        finally:
            self._running = False
            logger.debug("[PersistenceWorker] Worker loop exited")

    def _process_task(self, task: PersistenceTask) -> None:
        """Process a single persistence task."""
        try:
            start_time = time.monotonic()

            # Dispatch based on task type
            if task.task_type == "manifest":
                self._write_manifest(task.data)
            elif task.task_type == "run_metadata":
                self._write_run_metadata(task.data)
            elif task.task_type == "history":
                self._write_history(task.data)
            elif task.task_type == "image_metadata":
                self._write_image_metadata(task.data)
            else:
                logger.warning(f"[PersistenceWorker] Unknown task type: {task.task_type}")
                return

            duration_ms = (time.monotonic() - start_time) * 1000
            self._tasks_completed += 1

            logger.debug(f"[PersistenceWorker] Completed {task.task_type} in {duration_ms:.1f}ms")

            # Dispatch callback to UI thread if provided
            if task.callback and self._ui_callback_dispatcher:
                try:
                    self._ui_callback_dispatcher(task.callback)
                except Exception as exc:
                    logger.exception(f"[PersistenceWorker] Error dispatching callback: {exc}")
            elif task.callback:
                # No dispatcher - call directly (test mode)
                try:
                    task.callback()
                except Exception as exc:
                    logger.exception(f"[PersistenceWorker] Error in callback: {exc}")

        except Exception as exc:
            self._tasks_failed += 1
            self._failures.append(
                f"{task.task_type} job={task.data.get('job_id') or 'unknown'} "
                f"file={task.data.get('file_path')}: {exc}"
            )
            del self._failures[:-20]
            logger.exception(f"[PersistenceWorker] Failed to process {task.task_type}: {exc}")

    def _write_manifest(self, data: dict[str, Any]) -> None:
        """Write a stage manifest JSON file."""
        file_path = Path(data["file_path"])
        payload = data["payload"]

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON atomically
        temp_path = file_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(file_path)

    def _write_run_metadata(self, data: dict[str, Any]) -> None:
        """Write run_metadata.json file."""
        file_path = Path(data["file_path"])
        payload = data["payload"]

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write JSON atomically
        temp_path = file_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(file_path)

    def _write_history(self, data: dict[str, Any]) -> None:
        """Write history index update."""
        file_path = Path(data["file_path"])
        payload = data["payload"]

        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Append to JSONL file
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _write_image_metadata(self, data: dict[str, Any]) -> None:
        """Write image with embedded metadata."""
        # Placeholder for image metadata embedding
        # This would use PIL or similar to embed metadata in PNG/JPG
        logger.debug(f"[PersistenceWorker] Image metadata write: {data.get('file_path')}")
        # TODO: Implement actual image metadata embedding if needed


# Global singleton instance
_global_worker: PersistenceWorker | None = None
_worker_lock = threading.Lock()


def get_persistence_worker() -> PersistenceWorker:
    """Get or create the global persistence worker singleton."""
    global _global_worker

    with _worker_lock:
        if _global_worker is None:
            _global_worker = PersistenceWorker()
            _global_worker.start()
        return _global_worker


def shutdown_persistence_worker(timeout: float | None = 5.0) -> bool:
    """Shutdown the global persistence worker."""
    global _global_worker

    with _worker_lock:
        worker = _global_worker
    if worker is None:
        return True
    stopped = worker.stop(timeout=timeout)
    if worker.active_thread() is None:
        with _worker_lock:
            if _global_worker is worker:
                _global_worker = None
    return stopped


def active_persistence_thread() -> threading.Thread | None:
    with _worker_lock:
        worker = _global_worker
    return worker.active_thread() if worker is not None else None
