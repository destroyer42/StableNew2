"""
Tests for ThreadRegistry - Centralized Thread Lifecycle Management

PR-THREAD-001: Comprehensive test coverage for thread tracking and shutdown.
"""

import threading
import time
import pytest

from src.utils.thread_registry import (
    ThreadRegistry,
    get_thread_registry,
    shutdown_all_threads,
    TrackedThread,
)


class TestThreadRegistry:
    """Test ThreadRegistry singleton and thread tracking."""
    
    def test_singleton_pattern(self):
        """ThreadRegistry should be a singleton."""
        registry1 = ThreadRegistry()
        registry2 = ThreadRegistry()
        assert registry1 is registry2
    
    def test_get_thread_registry_returns_singleton(self):
        """get_thread_registry() should return the singleton instance."""
        registry1 = get_thread_registry()
        registry2 = get_thread_registry()
        assert registry1 is registry2
        assert isinstance(registry1, ThreadRegistry)
    
    def test_spawn_requires_name(self):
        """spawn() should require a thread name."""
        registry = get_thread_registry()
        
        def dummy_fn():
            pass
        
        with pytest.raises(ValueError, match="Thread name is required"):
            registry.spawn(target=dummy_fn, name=None)
    
    def test_spawn_creates_and_tracks_thread(self):
        """spawn() should create and track a thread."""
        registry = get_thread_registry()
        completion_flag = threading.Event()
        
        def worker():
            completion_flag.wait(timeout=0.5)
        
        thread = registry.spawn(
            target=worker,
            name="TestWorker",
            purpose="Test thread tracking"
        )
        
        assert thread.is_alive()
        assert thread.name == "TestWorker"
        
        # Check that thread is tracked
        active_threads = registry.get_active_threads()
        tracked_names = [t.name for t in active_threads]
        assert "TestWorker" in tracked_names
        
        # Cleanup
        completion_flag.set()
        thread.join(timeout=1.0)
    
    def test_spawn_with_args_and_kwargs(self):
        """spawn() should pass args and kwargs to target."""
        registry = get_thread_registry()
        result = {"value": None}
        done = threading.Event()
        
        def worker(x, y, z=10):
            result["value"] = x + y + z
            done.set()
        
        thread = registry.spawn(
            target=worker,
            args=(1, 2),
            kwargs={"z": 3},
            name="TestArgsWorker"
        )
        
        done.wait(timeout=1.0)
        assert result["value"] == 6
        
        thread.join(timeout=1.0)
    
    def test_spawn_warns_on_daemon_threads(self, caplog):
        """spawn() should warn when creating daemon threads."""
        import logging
        
        registry = get_thread_registry()
        done = threading.Event()
        
        def worker():
            done.wait(timeout=0.5)
        
        with caplog.at_level(logging.WARNING):
            thread = registry.spawn(
                target=worker,
                name="TestDaemonWorker",
                daemon=True
            )
        
        assert "daemon thread" in caplog.text.lower()
        assert thread.daemon is True
        
        done.set()
        thread.join(timeout=1.0)
    
    def test_get_active_threads_cleans_dead_threads(self):
        """get_active_threads() should remove dead threads from tracking."""
        registry = get_thread_registry()
        
        def quick_worker():
            time.sleep(0.1)
        
        thread = registry.spawn(
            target=quick_worker,
            name="QuickWorker"
        )
        
        # Wait for thread to complete
        thread.join(timeout=1.0)
        assert not thread.is_alive()
        
        # get_active_threads() should clean it up
        active_threads = registry.get_active_threads()
        tracked_names = [t.name for t in active_threads]
        assert "QuickWorker" not in tracked_names
    
    def test_unregister_removes_thread(self):
        """unregister() should remove a thread from tracking."""
        registry = get_thread_registry()
        done = threading.Event()
        
        def worker():
            done.wait(timeout=1.0)
        
        thread = registry.spawn(
            target=worker,
            name="UnregisterWorker"
        )
        
        # Verify tracked
        active = registry.get_active_threads()
        assert any(t.name == "UnregisterWorker" for t in active)
        
        # Unregister
        registry.unregister(thread)
        
        # Verify no longer tracked
        active = registry.get_active_threads()
        assert not any(t.name == "UnregisterWorker" for t in active)
        
        # Cleanup
        done.set()
        thread.join(timeout=1.0)
    
    def test_shutdown_all_joins_non_daemon_threads(self):
        """shutdown_all() should join all non-daemon threads."""
        registry = get_thread_registry()
        worker_started = threading.Event()
        shutdown_flag = threading.Event()
        
        def worker():
            worker_started.set()
            shutdown_flag.wait(timeout=5.0)
        
        thread = registry.spawn(
            target=worker,
            name="ShutdownWorker",
            daemon=False
        )
        
        # Wait for worker to start
        worker_started.wait(timeout=1.0)
        
        # Signal shutdown
        shutdown_flag.set()
        
        # Shutdown registry
        stats = registry.shutdown_all(timeout=2.0)
        
        assert stats["total"] >= 1
        assert stats["joined"] >= 1
        assert stats["timeout"] == 0
        assert not thread.is_alive()
    
    def test_shutdown_all_reports_timeout_threads(self):
        """shutdown_all() should report threads that don't shut down."""
        registry = get_thread_registry()
        worker_started = threading.Event()
        
        def worker():
            worker_started.set()
            time.sleep(10.0)  # Sleep longer than timeout
        
        thread = registry.spawn(
            target=worker,
            name="TimeoutWorker",
            daemon=False
        )
        
        worker_started.wait(timeout=1.0)
        
        # Shutdown with short timeout
        stats = registry.shutdown_all(timeout=0.5)
        
        assert stats["timeout"] >= 1
        assert thread.is_alive()  # Thread should still be running
        
        # Cleanup - give thread a chance to finish
        time.sleep(0.5)
    
    def test_shutdown_all_reports_orphaned_daemon_threads(self):
        """shutdown_all() should report daemon threads still alive."""
        registry = get_thread_registry()
        worker_started = threading.Event()
        
        def worker():
            worker_started.set()
            time.sleep(10.0)
        
        thread = registry.spawn(
            target=worker,
            name="OrphanDaemonWorker",
            daemon=True
        )
        
        worker_started.wait(timeout=1.0)
        
        stats = registry.shutdown_all(timeout=0.5)
        
        assert stats["orphaned"] >= 1
        assert thread.is_alive()  # Daemon still running
    
    def test_is_shutdown_requested_flag(self):
        """is_shutdown_requested() should return shutdown state."""
        registry = get_thread_registry()
        
        # Reset shutdown flag for test isolation
        registry._shutdown_requested = False
        
        assert not registry.is_shutdown_requested()
        
        # Trigger shutdown
        registry.shutdown_all(timeout=0.1)
        
        assert registry.is_shutdown_requested()
    
    def test_dump_status_shows_thread_info(self):
        """dump_status() should return human-readable thread status."""
        registry = get_thread_registry()
        done = threading.Event()
        
        def worker():
            done.wait(timeout=1.0)
        
        thread = registry.spawn(
            target=worker,
            name="StatusWorker",
            purpose="Testing status dump"
        )
        
        status = registry.dump_status()
        
        assert "StatusWorker" in status
        assert "alive" in status
        assert "Testing status dump" in status
        
        # Cleanup
        done.set()
        thread.join(timeout=1.0)
    
    def test_tracked_thread_dataclass(self):
        """TrackedThread should store thread metadata."""
        thread = threading.Thread(target=lambda: None, name="TestThread")
        
        tracked = TrackedThread(
            thread=thread,
            name="TestThread",
            spawned_at=time.monotonic(),
            purpose="Test purpose"
        )
        
        assert tracked.thread == thread
        assert tracked.name == "TestThread"
        assert tracked.purpose == "Test purpose"
        assert tracked.spawned_at > 0
    
    def test_shutdown_all_threads_convenience_function(self):
        """shutdown_all_threads() should work as convenience wrapper."""
        registry = get_thread_registry()
        done = threading.Event()
        
        def worker():
            done.wait(timeout=1.0)
        
        thread = registry.spawn(
            target=worker,
            name="ConvenienceWorker"
        )
        
        done.set()
        stats = shutdown_all_threads(timeout=2.0)
        
        assert "total" in stats
        assert "joined" in stats
        assert not thread.is_alive()


class TestThreadRegistryIntegration:
    """Integration tests for ThreadRegistry with realistic scenarios."""
    
    def test_multiple_workers_shutdown_cleanly(self):
        """Multiple workers should all shutdown cleanly."""
        registry = get_thread_registry()
        
        # Clear registry state from previous tests
        registry._threads.clear()
        registry._shutdown_requested = False
        
        num_workers = 5
        workers_done = [threading.Event() for _ in range(num_workers)]
        
        def worker(idx):
            workers_done[idx].wait(timeout=5.0)
        
        threads = []
        for i in range(num_workers):
            thread = registry.spawn(
                target=worker,
                args=(i,),
                name=f"Worker-{i}",
                daemon=False
            )
            threads.append(thread)
        
        # Signal all workers to finish
        for event in workers_done:
            event.set()
        
        # Shutdown
        stats = registry.shutdown_all(timeout=2.0)
        
        assert stats["joined"] >= num_workers
        assert stats["timeout"] == 0
        
        for thread in threads:
            assert not thread.is_alive()
    
    def test_shutdown_with_mixed_daemon_and_normal_threads(self):
        """Shutdown should handle mix of daemon and normal threads."""
        registry = get_thread_registry()
        done = threading.Event()
        
        def worker():
            done.wait(timeout=5.0)
        
        # Spawn mix of daemon and normal threads
        normal_thread = registry.spawn(
            target=worker,
            name="NormalThread",
            daemon=False
        )
        
        daemon_thread = registry.spawn(
            target=worker,
            name="DaemonThread",
            daemon=True
        )
        
        done.set()
        
        stats = registry.shutdown_all(timeout=2.0)
        
        assert stats["joined"] >= 1  # Normal thread
        # Daemon may be counted as orphaned if still running
        assert not normal_thread.is_alive()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
