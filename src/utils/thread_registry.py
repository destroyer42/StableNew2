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
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class TrackedThread:
    """Information about a tracked thread."""
    thread: threading.Thread
    name: str
    spawned_at: float
    purpose: str | None = None


class ThreadRegistry:
    """
    Singleton registry for tracking all background threads.
    
    This class ensures:
    - All threads are tracked and can be joined during shutdown
    - No daemon threads are left orphaned
    - Thread status is inspectable for debugging
    """
    
    _instance: "ThreadRegistry | None" = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "ThreadRegistry":
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
        self._initialized = True
        logger.info("[thread_registry] Thread registry initialized")
    
    def spawn(
        self,
        target: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
        name: str | None = None,
        daemon: bool = False,
        purpose: str | None = None,
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
        
        Returns:
            The spawned and started thread
        
        Raises:
            ValueError: If name is not provided
        """
        if kwargs is None:
            kwargs = {}
        
        if name is None:
            raise ValueError("Thread name is required for tracking")
        
        if daemon:
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
        
        tracked = TrackedThread(
            thread=thread,
            name=name,
            spawned_at=time.monotonic(),
            purpose=purpose,
        )
        
        with self._registry_lock:
            # Remove any dead threads before adding new one
            self._cleanup_dead_threads()
            
            # Add new thread
            thread.start()
            self._threads[id(thread)] = tracked
            
            logger.debug(
                f"[thread_registry] Spawned thread '{name}' "
                f"(id={id(thread)}, daemon={daemon})"
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
                    f"[thread_registry] Unregistered thread '{tracked.name}' "
                    f"(id={thread_id})"
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
                f"[thread_registry] Cleaned up dead thread '{tracked.name}' "
                f"(id={thread_id})"
            )
    
    def shutdown_all(self, timeout: float = 10.0) -> dict[str, Any]:
        """
        Gracefully shutdown all tracked threads.
        
        This method:
        1. Marks shutdown as requested (threads should check this)
        2. Joins all non-daemon threads with timeout
        3. Reports any threads that didn't shut down cleanly
        
        Args:
            timeout: Maximum time to wait for each thread (seconds)
        
        Returns:
            Dict with shutdown statistics:
                - total: Total threads tracked
                - joined: Threads that shutdown cleanly
                - timeout: Threads that timed out
                - orphaned: Daemon threads still alive
        """
        logger.info(
            f"[thread_registry] Shutdown requested for all threads "
            f"(timeout={timeout}s)"
        )
        
        self._shutdown_requested = True
        
        with self._registry_lock:
            threads_to_join = list(self._threads.values())
        
        stats = {
            "total": len(threads_to_join),
            "joined": 0,
            "timeout": 0,
            "orphaned": 0,
        }
        
        # Join all threads
        for tracked in threads_to_join:
            thread = tracked.thread
            
            if thread.daemon:
                if thread.is_alive():
                    logger.warning(
                        f"[thread_registry] Daemon thread '{tracked.name}' "
                        f"still alive (age={time.monotonic() - tracked.spawned_at:.1f}s)"
                    )
                    stats["orphaned"] += 1
                continue
            
            if not thread.is_alive():
                stats["joined"] += 1
                continue
            
            logger.debug(
                f"[thread_registry] Joining thread '{tracked.name}' "
                f"(timeout={timeout}s)"
            )
            
            thread.join(timeout=timeout)
            
            if thread.is_alive():
                logger.error(
                    f"[thread_registry] Thread '{tracked.name}' did not "
                    f"shutdown within {timeout}s timeout!"
                )
                stats["timeout"] += 1
            else:
                logger.debug(
                    f"[thread_registry] Thread '{tracked.name}' shutdown cleanly"
                )
                stats["joined"] += 1
        
        # Final cleanup
        with self._registry_lock:
            self._cleanup_dead_threads()
            remaining = len(self._threads)
        
        if remaining > 0:
            logger.warning(
                f"[thread_registry] {remaining} thread(s) still tracked after shutdown"
            )
        else:
            logger.info("[thread_registry] All threads shutdown successfully")
        
        return stats
    
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
            
            line = (
                f"  - {tracked.name} ({daemon}, {alive}, age={age:.1f}s)"
            )
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
        timeout: Maximum time to wait for each thread
    
    Returns:
        Shutdown statistics dict
    """
    registry = get_thread_registry()
    return registry.shutdown_all(timeout=timeout)
