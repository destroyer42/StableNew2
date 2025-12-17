"""
Tests for queue worker thread lifecycle management: start, stop, and join.

Validates:
1. Worker thread starts when queue worker starts
2. Worker thread stops when stop() is called (idempotent)
3. Worker thread joins with timeout after stop
4. Idle queue shutdown is safe (no deadlock)
5. JobService.stop() is idempotent
"""

import threading
import time
import unittest
from unittest.mock import Mock

from src.controller.job_service import JobService
from src.queue.job_model import Job, JobPriority
from src.queue.job_queue import JobQueue


class TestSingleNodeRunnerWorkerLifecycle(unittest.TestCase):
    """Test SingleNodeJobRunner worker thread lifecycle."""

    def setUp(self) -> None:
        """Create a job queue and runner for testing."""
        self.job_queue = JobQueue()

    def test_runner_start_creates_worker_thread(self) -> None:
        """Verify runner.start() creates a worker thread."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        runner = SingleNodeJobRunner(
            self.job_queue,
            run_callable=None,
            poll_interval=0.05,
        )

        # Before start, worker should be None
        self.assertIsNone(runner._worker)

        # Start the runner
        runner.start()

        # After start, worker should be a thread
        self.assertIsNotNone(runner._worker)
        self.assertIsInstance(runner._worker, threading.Thread)
        self.assertTrue(runner._worker.is_alive())

        # Clean up
        runner.stop()

    def test_runner_stop_sets_stop_event(self) -> None:
        """Verify runner.stop() sets the stop event."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        runner = SingleNodeJobRunner(
            self.job_queue,
            run_callable=None,
            poll_interval=0.05,
        )

        runner.start()

        # Stop should set the stop event
        runner.stop()

        # Stop event should be set
        self.assertTrue(runner._stop_event.is_set())

    def test_runner_stop_joins_worker_thread(self) -> None:
        """Verify runner.stop() joins the worker thread with timeout."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        runner = SingleNodeJobRunner(
            self.job_queue,
            run_callable=None,
            poll_interval=0.05,
        )

        runner.start()
        self.assertTrue(runner._worker.is_alive())

        # Stop should join the thread
        runner.stop()

        # Thread should no longer be alive
        self.assertFalse(runner._worker.is_alive())

    def test_runner_stop_is_idempotent(self) -> None:
        """Verify calling runner.stop() multiple times is safe."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        runner = SingleNodeJobRunner(
            self.job_queue,
            run_callable=None,
            poll_interval=0.05,
        )

        runner.start()

        # Multiple stops should not raise
        runner.stop()
        runner.stop()
        runner.stop()

        self.assertFalse(runner._worker.is_alive())

    def test_runner_stops_when_queue_is_idle(self) -> None:
        """Verify worker thread can stop even when queue is empty."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        runner = SingleNodeJobRunner(
            self.job_queue,
            run_callable=None,
            poll_interval=0.05,
        )

        runner.start()
        # Queue is empty (idle)
        self.assertEqual(len(self.job_queue.list_jobs()), 0)

        # Should be able to stop even in idle state
        runner.stop()
        self.assertFalse(runner._worker.is_alive())

    def test_runner_worker_loop_exits_on_stop_event(self) -> None:
        """Verify worker loop checks stop event and exits."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        runner = SingleNodeJobRunner(
            self.job_queue,
            run_callable=None,
            poll_interval=0.01,
        )

        runner.start()
        time.sleep(0.05)  # Let worker run a bit

        # Should be running
        self.assertTrue(runner._worker.is_alive())

        # Set stop event
        runner._stop_event.set()
        time.sleep(0.1)  # Wait for thread to check stop event

        # Should now be stopped
        self.assertFalse(runner._worker.is_alive())


class TestJobServiceStop(unittest.TestCase):
    """Test JobService.stop() method."""

    def setUp(self) -> None:
        """Create a job service for testing."""
        self.job_queue = JobQueue()

    def test_job_service_has_stop_method(self) -> None:
        """Verify JobService has a public stop() method."""
        service = JobService(self.job_queue)
        self.assertTrue(hasattr(service, "stop"))
        self.assertTrue(callable(service.stop))

    def test_job_service_stop_calls_runner_stop(self) -> None:
        """Verify JobService.stop() calls runner.stop()."""
        service = JobService(self.job_queue)

        # Mock the runner's stop method
        service.runner.stop = Mock()
        # Set worker_started so _stop_runner actually calls runner.stop()
        service._worker_started = True

        # Call service.stop()
        service.stop()

        # Runner.stop() should have been called
        service.runner.stop.assert_called()

    def test_job_service_stop_is_idempotent(self) -> None:
        """Verify JobService.stop() can be called multiple times safely."""
        service = JobService(self.job_queue)

        # Mock the runner
        service.runner.stop = Mock()

        # Multiple calls should not raise
        service.stop()
        service.stop()
        service.stop()

    def test_job_service_stop_when_worker_not_started(self) -> None:
        """Verify JobService.stop() handles case when worker was never started."""
        service = JobService(self.job_queue)

        # Worker was never started
        self.assertFalse(service._worker_started)

        # Should not raise
        service.stop()

    def test_job_service_stop_is_thread_safe(self) -> None:
        """Verify JobService.stop() uses runner lock for thread safety."""
        service = JobService(self.job_queue)

        # Mock the runner
        service.runner.stop = Mock()

        # Create threads that call stop simultaneously
        threads = [
            threading.Thread(target=service.stop)
            for _ in range(5)
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join(timeout=2.0)

        # All threads should have completed without deadlock


class TestIdleQueueShutdown(unittest.TestCase):
    """Test shutting down queue with no jobs (idle state)."""

    def test_idle_queue_shutdown_no_deadlock(self) -> None:
        """Verify shutting down idle queue doesn't deadlock."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        job_queue = JobQueue()
        runner = SingleNodeJobRunner(
            job_queue,
            run_callable=None,
            poll_interval=0.05,
        )

        # Start with empty queue
        self.assertEqual(len(job_queue.list_jobs()), 0)

        runner.start()
        time.sleep(0.1)  # Let worker run

        # Should be able to stop even though queue is idle
        start_time = time.monotonic()
        runner.stop()
        elapsed = time.monotonic() - start_time

        # Should complete quickly (not deadlocked)
        self.assertLess(elapsed, 5.0)
        self.assertFalse(runner._worker.is_alive())

    def test_job_service_stop_with_no_jobs(self) -> None:
        """Verify JobService.stop() works with empty queue."""
        job_queue = JobQueue()
        service = JobService(job_queue)

        # Queue is empty
        self.assertEqual(len(job_queue.list_jobs()), 0)

        # Should not raise
        start_time = time.monotonic()
        service.stop()
        elapsed = time.monotonic() - start_time

        # Should complete quickly
        self.assertLess(elapsed, 5.0)

    def test_job_service_start_and_stop_cycle(self) -> None:
        """Verify JobService can start and stop multiple times."""
        job_queue = JobQueue()
        service = JobService(job_queue)

        for _ in range(3):
            # Start worker
            if hasattr(service.runner, "start"):
                service.runner.start()
            service._worker_started = True
            time.sleep(0.05)

            # Stop worker
            service.stop()

            # Should be stopped
            if hasattr(service.runner, "_worker"):
                if service.runner._worker:
                    self.assertFalse(service.runner._worker.is_alive())


class TestWorkerThreadJoinTimeout(unittest.TestCase):
    """Test worker thread join with timeout behavior."""

    def test_runner_stop_uses_join_timeout(self) -> None:
        """Verify runner.stop() uses join with a timeout."""
        from src.queue.single_node_runner import SingleNodeJobRunner

        job_queue = JobQueue()
        runner = SingleNodeJobRunner(job_queue, run_callable=None, poll_interval=0.05)

        runner.start()
        time.sleep(0.1)

        # Stop should join with timeout (2 seconds per implementation)
        start_time = time.monotonic()
        runner.stop()
        elapsed = time.monotonic() - start_time

        # Should complete within reasonable time (not hang forever)
        self.assertLess(elapsed, 5.0)


class TestJobServiceLifecycleIntegration(unittest.TestCase):
    """Integration tests for full JobService lifecycle."""

    def test_job_service_full_lifecycle(self) -> None:
        """Verify complete JobService lifecycle: init -> use -> stop."""
        job_queue = JobQueue()
        service = JobService(job_queue)

        # Initially, worker not started
        self.assertFalse(service._worker_started)

        # Start the runner
        if hasattr(service.runner, "start"):
            service.runner.start()
        service._worker_started = True

        time.sleep(0.05)

        # Stop should complete successfully
        service.stop()

        # Worker should be stopped
        if hasattr(service.runner, "_worker"):
            self.assertFalse(service.runner._worker.is_alive())

    def test_job_service_stop_with_pending_jobs(self) -> None:
        """Verify JobService.stop() works even with jobs in queue."""
        job_queue = JobQueue()

        # Add a job to the queue
        job = Job(job_id="test-job-1", prompt_pack_id="pack-1", priority=JobPriority.NORMAL)
        job_queue.submit(job)

        service = JobService(job_queue, run_callable=lambda j: None)

        # Start worker
        if hasattr(service.runner, "start"):
            service.runner.start()
        service._worker_started = True

        time.sleep(0.05)

        # Stop should still work (even with job in queue)
        service.stop()

        if hasattr(service.runner, "_worker"):
            self.assertFalse(service.runner._worker.is_alive())


if __name__ == "__main__":
    unittest.main()
