"""
Thread Registry for Centralized Thread Lifecycle Management

PR-THREAD-001: Implements a singleton thread registry to track all background
threads and ensure clean shutdown without zombie processes.

This module provides:
- Centralized thread spawning via spawn()
- Automatic thread tracking and cleanup
- Graceful shutdown with configurable timeouts
- Thread status inspection for debugging

Usage:
    from src.utils.thread_registry import get_thread_registry

    registry = get_thread_registry()
    thread = registry.spawn(
        target=my_function,
        args=(arg1, arg2),
        name="MyBackgroundWorker"
    )

    # Later during shutdown:
    registry.shutdown_all(timeout=10.0)
"""

import logging
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrackedThread:
    """Information about a tracked thread."""

    thread: threading.Thread
    name: str
    spawned_at: float
    purpose: str | None = None
    suppress_daemon_warning: bool = False


class ThreadRegistry:
    """
    Singleton registry for tracking all background threads.

    This class ensures:
    - All threads are tracked and can be joined during shutdown
    - No daemon threads are left orphaned
    - Thread status is inspectable for debugging
    """

    _instance: ThreadRegistry | None = None
    _lock = threading.Lock()

    def __new__(cls) -> ThreadRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._threads: dict[int, TrackedThread] = {}
        self._registry_lock = threading.Lock()
        self._shutdown_requested = False
        self._shutdown_listeners: list[Callable[[], None]] = []
        self._initialized = True
        logger.info("[thread_registry] Thread registry initialized")

    def add_shutdown_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Run ``listener`` when ``shutdown_all`` starts, before any thread is joined.

        A long-running worker registers its own cancel here so the join does not wait out work nobody asked
        for.  The listener runs on the shutting-down thread and must only signal (set an event); it must
        not wait for the GUI.  Returns a callable that removes the listener (safe to call more than once).
        """

        with self._registry_lock:
            already_shutting_down = self._shutdown_requested
            if not already_shutting_down:
                self._shutdown_listeners.append(listener)
        if already_shutting_down:
            listener()

        def remove() -> None:
            with self._registry_lock:
                try:
                    self._shutdown_listeners.remove(listener)
                except ValueError:
                    pass

        return remove

    def spawn(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        name: str | None = None,
        daemon: bool = False,
        purpose: str | None = None,
        suppress_daemon_warning: bool = False,
    ) -> threading.Thread:
        """
        Spawn a new tracked thread.

        Args:
            target: The callable to run in the thread
            args: Positional arguments for target
            kwargs: Keyword arguments for target
            name: Thread name (required for tracking)
            daemon: Whether to use daemon mode (discouraged)
            purpose: Human-readable description of thread purpose
            suppress_daemon_warning: If True, don't warn about daemon=True

        Returns:
            The spawned and started thread

        Raises:
            ValueError: If name is not provided
        """
        if kwargs is None:
            kwargs = {}

        if name is None:
            raise ValueError("Thread name is required for tracking")

        if daemon and not suppress_daemon_warning:
            logger.warning(
                f"[thread_registry] Spawning daemon thread '{name}' - "
                f"consider using daemon=False for clean shutdown"
            )

        thread = threading.Thread(
            target=target,
            args=args,
            kwargs=kwargs,
            name=name,
            daemon=daemon,
        )

        return self.start_tracked_thread(thread, purpose, suppress_daemon_warning=suppress_daemon_warning)

    def start_tracked_thread(
        self, thread: threading.Thread, purpose: str | None, *, suppress_daemon_warning: bool = False,
    ) -> threading.Thread:
        """Start and register an existing Thread subclass under the same admission fence."""
        tracked = TrackedThread(
            thread=thread,
            name=thread.name,
            spawned_at=time.monotonic(),
            purpose=purpose,
            suppress_daemon_warning=suppress_daemon_warning,
        )

        with self._registry_lock:
            if self._shutdown_requested:
                raise RuntimeError("Thread registry is shutting down")
            # Remove any dead threads before adding new one
            self._cleanup_dead_threads()

            # Add new thread
            thread.start()
            self._threads[id(thread)] = tracked

            logger.debug(
                "[thread_registry] Started thread '%s' (ident=%s)", thread.name, thread.ident,
            )

        return thread

    def unregister(self, thread: threading.Thread) -> None:
        """
        Manually unregister a thread (usually not needed).

        Args:
            thread: Thread to unregister
        """
        with self._registry_lock:
            thread_id = id(thread)
            if thread_id in self._threads:
                tracked = self._threads.pop(thread_id)
                logger.debug(
                    f"[thread_registry] Unregistered thread '{tracked.name}' (id={thread_id})"
                )

    def get_active_threads(self) -> list[TrackedThread]:
        """
        Get list of all currently tracked threads.

        Returns:
            List of TrackedThread instances for active threads
        """
        with self._registry_lock:
            self._cleanup_dead_threads()
            return list(self._threads.values())

    def _cleanup_dead_threads(self) -> None:
        """Remove dead threads from registry (called with lock held)."""
        dead_ids = [
            thread_id
            for thread_id, tracked in self._threads.items()
            if not tracked.thread.is_alive()
        ]

        for thread_id in dead_ids:
            tracked = self._threads.pop(thread_id)
            logger.debug(
                f"[thread_registry] Cleaned up dead thread '{tracked.name}' (id={thread_id})"
            )

    def begin_shutdown(self) -> None:
        """Fence new tracked work and notify each registered stop listener once."""
        with self._registry_lock:
            if self._shutdown_requested:
                return
            self._shutdown_requested = True
            listeners = list(self._shutdown_listeners)
        for listener in listeners:
            try:
                listener()
            except Exception:
                logger.exception("[thread_registry] shutdown listener failed")

    def shutdown_all(self, timeout: float = 10.0) -> dict[str, Any]:
        """Signal stops and join non-daemon threads within one aggregate budget."""
        deadline = time.monotonic() + max(0.0, timeout)
        self.begin_shutdown()
        tracked_threads = self.get_active_threads()
        current = threading.current_thread()
        for tracked in tracked_threads:
            thread = tracked.thread
            if not thread.daemon and thread is not current:
                thread.join(timeout=max(0.0, deadline - time.monotonic()))

        surviving = self.get_active_threads()
        timeouts = sum(not item.thread.daemon for item in surviving)
        orphans = sum(item.thread.daemon and not item.suppress_daemon_warning for item in surviving)
        for item in surviving:
            if not item.thread.daemon:
                logger.error("[thread_registry] Thread '%s' did not shutdown within the shared deadline", item.name)
            elif not item.suppress_daemon_warning:
                logger.warning("[thread_registry] Daemon thread '%s' still alive", item.name)
        return {
            "total": len(tracked_threads),
            "joined": sum(not item.thread.daemon and not item.thread.is_alive() for item in tracked_threads),
            "timeout": timeouts,
            "orphaned": orphans,
        }

    def is_shutdown_requested(self) -> bool:
        """
        Check if shutdown has been requested.

        Background threads should periodically check this and exit cleanly.

        Returns:
            True if shutdown was requested
        """
        return self._shutdown_requested

    def dump_status(self) -> str:
        """
        Generate human-readable status report of all threads.

        Returns:
            Multi-line string with thread status
        """
        with self._registry_lock:
            self._cleanup_dead_threads()
            threads = list(self._threads.values())

        if not threads:
            return "[thread_registry] No active threads"

        lines = [f"[thread_registry] {len(threads)} active thread(s):"]

        now = time.monotonic()
        for tracked in threads:
            age = now - tracked.spawned_at
            alive = "alive" if tracked.thread.is_alive() else "dead"
            daemon = "daemon" if tracked.thread.daemon else "normal"

            line = f"  - {tracked.name} ({daemon}, {alive}, age={age:.1f}s)"
            if tracked.purpose:
                line += f" - {tracked.purpose}"
            lines.append(line)

        return "\n".join(lines)


# Global singleton accessor
_global_registry: ThreadRegistry | None = None
_global_lock = threading.Lock()


def get_thread_registry() -> ThreadRegistry:
    """
    Get the global thread registry singleton.

    Returns:
        The ThreadRegistry instance
    """
    global _global_registry

    if _global_registry is None:
        with _global_lock:
            if _global_registry is None:
                _global_registry = ThreadRegistry()

    return _global_registry


def shutdown_all_threads(timeout: float = 10.0) -> dict[str, Any]:
    """
    Convenience function to shutdown all tracked threads.

    Args:
        timeout: Maximum time to wait across all threads

    Returns:
        Shutdown statistics dict
    """
    registry = get_thread_registry()
    return registry.shutdown_all(timeout=timeout)


def log_worker_stacks(workers: Iterable[tuple[threading.Thread, str]], *, phase: str) -> None:
    """Sample a bounded stack of surviving workers without reading source or frame locals."""
    active = [(thread, role) for thread, role in workers if thread.is_alive()]
    if not active:
        return
    frames = sys._current_frames()
    for thread, role in active[:12]:
        frame = frames.get(thread.ident) if thread.ident is not None else None
        stack = []
        while frame is not None and len(stack) < 8:
            code = frame.f_code
            stack.append(f"{Path(code.co_filename).name}:{frame.f_lineno}:{code.co_name}")
            frame = frame.f_back
        logger.warning(
            "[shutdown] phase=%s worker=%s ident=%s role=%s stack=%s",
            phase, thread.name, thread.ident, role, " <- ".join(stack),
        )
