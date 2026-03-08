"""
Integration Tests for Clean Shutdown Sequence

PR-SHUTDOWN-001: Verify no orphan threads or zombie processes after shutdown.
"""

import threading
import time
import pytest
import psutil
import os

from src.utils.thread_registry import get_thread_registry, shutdown_all_threads


class TestCleanShutdown:
    """Verify complete shutdown with no orphan threads or zombies."""
    
    def test_no_orphan_threads_after_registry_shutdown(self):
        """After registry shutdown, no tracked threads should remain alive."""
        registry = get_thread_registry()
        
        # Clear any existing threads
        registry.shutdown_all(timeout=1.0)
        
        # Spawn test threads
        completion_flags = []
        for i in range(3):
            flag = threading.Event()
            completion_flags.append(flag)
            
            def worker(idx=i, event=flag):
                event.wait(timeout=5.0)
            
            registry.spawn(
                target=worker,
                name=f"TestWorker-{i}",
                daemon=False
            )
        
        # Verify threads are running
        active = registry.get_active_threads()
        assert len(active) >= 3
        
        # Signal shutdown
        for flag in completion_flags:
            flag.set()
        
        # Execute shutdown
        stats = registry.shutdown_all(timeout=5.0)
        
        # Verify all threads joined
        assert stats["timeout"] == 0, f"Threads timed out: {stats}"
        assert stats["orphaned"] == 0, f"Orphaned threads: {stats}"
        
        # Verify no tracked threads remain alive
        active_after = registry.get_active_threads()
        alive_threads = [t for t in active_after if t.thread.is_alive()]
        assert len(alive_threads) == 0, f"Threads still alive: {[t.name for t in alive_threads]}"
    
    def test_thread_count_matches_before_and_after(self):
        """Thread count should return to baseline after shutdown."""
        # Get baseline thread count
        baseline_count = threading.active_count()
        
        registry = get_thread_registry()
        registry.shutdown_all(timeout=1.0)
        
        # Spawn and shutdown threads
        done = threading.Event()
        
        def worker():
            done.wait(timeout=5.0)
        
        for i in range(5):
            registry.spawn(
                target=worker,
                name=f"CountTestWorker-{i}",
                daemon=False
            )
        
        # Verify threads running
        peak_count = threading.active_count()
        assert peak_count > baseline_count
        
        # Shutdown
        done.set()
        registry.shutdown_all(timeout=5.0)
        
        # Wait for thread cleanup
        time.sleep(0.5)
        
        # Verify thread count returned to baseline (or close to it)
        final_count = threading.active_count()
        # Allow for small variance due to test framework threads
        assert abs(final_count - baseline_count) <= 2, \
            f"Thread leak detected: baseline={baseline_count}, final={final_count}"
    
    def test_no_zombie_processes_after_shutdown(self):
        """After shutdown, no zombie child processes should exist."""
        current_pid = os.getpid()
        current_process = psutil.Process(current_pid)
        
        # Get baseline child processes
        baseline_children = current_process.children(recursive=True)
        baseline_count = len(baseline_children)
        
        registry = get_thread_registry()
        registry.shutdown_all(timeout=1.0)
        
        # Spawn threads that might interact with processes
        done = threading.Event()
        
        def worker():
            done.wait(timeout=5.0)
        
        for i in range(3):
            registry.spawn(
                target=worker,
                name=f"ProcessTestWorker-{i}",
                daemon=False
            )
        
        # Shutdown
        done.set()
        stats = registry.shutdown_all(timeout=5.0)
        
        # Wait for cleanup
        time.sleep(0.5)
        
        # Check for zombie children
        current_children = current_process.children(recursive=True)
        zombies = [p for p in current_children if p.status() == psutil.STATUS_ZOMBIE]
        
        assert len(zombies) == 0, f"Zombie processes detected: {[p.pid for p in zombies]}"
        
        # Verify child count returned to baseline (allow small variance)
        final_count = len(current_children)
        assert abs(final_count - baseline_count) <= 1, \
            f"Child process leak: baseline={baseline_count}, final={final_count}"
    
    def test_daemon_threads_do_not_prevent_shutdown(self):
        """Daemon threads should not block shutdown (but should be reported as orphaned)."""
        registry = get_thread_registry()
        registry.shutdown_all(timeout=1.0)
        
        # Spawn daemon thread that takes a long time
        def slow_daemon_worker():
            time.sleep(10.0)
        
        daemon_thread = registry.spawn(
            target=slow_daemon_worker,
            name="SlowDaemonWorker",
            daemon=True
        )
        
        # Shutdown with short timeout
        start = time.monotonic()
        stats = registry.shutdown_all(timeout=1.0)
        elapsed = time.monotonic() - start
        
        # Shutdown should not wait for daemon threads
        assert elapsed < 2.0, f"Shutdown took too long: {elapsed}s"
        
        # Daemon should be reported as orphaned
        assert stats["orphaned"] >= 1, f"Daemon not reported as orphaned: {stats}"
        
        # Daemon may still be running (that's OK, it's a daemon)
        # But it should not prevent the test from completing
    
    def test_shutdown_is_idempotent(self):
        """Calling shutdown_all() multiple times should be safe."""
        registry = get_thread_registry()
        
        # Clear any lingering threads from previous tests
        registry._threads.clear()
        registry._shutdown_requested = False
        
        done = threading.Event()
        
        def worker():
            done.wait(timeout=5.0)
        
        registry.spawn(
            target=worker,
            name="IdempotentWorker",
            daemon=False
        )
        
        done.set()
        
        # First shutdown
        stats1 = registry.shutdown_all(timeout=2.0)
        assert stats1["joined"] >= 1
        
        # Second shutdown (should be no-op)
        stats2 = registry.shutdown_all(timeout=2.0)
        assert stats2["total"] == 0  # No threads to shut down
        
        # Third shutdown
        stats3 = registry.shutdown_all(timeout=2.0)
        assert stats3["total"] == 0


class TestRealWorldShutdownScenarios:
    """Test shutdown scenarios that mirror real application usage."""
    
    def test_shutdown_with_io_bound_threads(self):
        """Threads doing I/O should shut down cleanly."""
        registry = get_thread_registry()
        registry.shutdown_all(timeout=1.0)
        
        shutdown_flag = threading.Event()
        
        def io_worker():
            """Simulate I/O-bound work."""
            while not shutdown_flag.is_set():
                # Simulate reading from file/network
                time.sleep(0.1)
        
        for i in range(3):
            registry.spawn(
                target=io_worker,
                name=f"IOWorker-{i}",
                daemon=False
            )
        
        # Let workers run briefly
        time.sleep(0.3)
        
        # Shutdown
        shutdown_flag.set()
        stats = registry.shutdown_all(timeout=5.0)
        
        assert stats["timeout"] == 0, "I/O threads failed to shut down"
        assert stats["joined"] >= 3
    
    def test_shutdown_with_cpu_bound_threads(self):
        """CPU-bound threads should respect shutdown signals."""
        registry = get_thread_registry()
        registry.shutdown_all(timeout=1.0)
        
        shutdown_flag = threading.Event()
        
        def cpu_worker():
            """Simulate CPU-bound work."""
            counter = 0
            while not shutdown_flag.is_set():
                # Simulate computation
                counter += 1
                if counter % 10000 == 0:
                    time.sleep(0.001)  # Yield occasionally
        
        for i in range(2):
            registry.spawn(
                target=cpu_worker,
                name=f"CPUWorker-{i}",
                daemon=False
            )
        
        # Let workers run briefly
        time.sleep(0.3)
        
        # Shutdown
        shutdown_flag.set()
        stats = registry.shutdown_all(timeout=5.0)
        
        assert stats["timeout"] == 0, "CPU threads failed to shut down"
        assert stats["joined"] >= 2
    
    def test_shutdown_with_exception_in_thread(self):
        """Threads that crash should not prevent clean shutdown."""
        registry = get_thread_registry()
        registry.shutdown_all(timeout=1.0)
        
        def crashing_worker():
            time.sleep(0.1)
            raise RuntimeError("Intentional crash for testing")
        
        thread = registry.spawn(
            target=crashing_worker,
            name="CrashingWorker",
            daemon=False
        )
        
        # Wait for thread to crash
        thread.join(timeout=1.0)
        
        # Shutdown should still work
        stats = registry.shutdown_all(timeout=2.0)
        
        # Thread should be cleaned up (already dead)
        assert stats["timeout"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
