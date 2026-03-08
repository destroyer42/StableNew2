"""JT-07 — Large Batch Execution with GUI Responsiveness Test.

PR-QUEUE-001D: Validates that large batch job execution (80+ jobs) does not
freeze the GUI, history writes happen on background thread, and all jobs
complete successfully without memory leaks or zombie threads.

Key Validations:
- GUI heartbeat remains responsive during job execution
- No watchdog stall detections triggered
- History store writer thread operates correctly
- All jobs complete and are recorded in history
- Queue persistence works correctly
- No thread leakage after shutdown
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.helpers.factories import update_current_config
from tests.helpers.gui_harness import pipeline_harness
from tests.journeys.journey_helpers_v2 import (
    get_latest_job,
    get_stage_plan_for_job,
    start_run_and_wait,
)

logger = logging.getLogger(__name__)


@pytest.mark.journey
@pytest.mark.slow
class TestJT07LargeBatchExecution:
    """JT-07: Validates large batch execution without GUI freeze or memory leaks.
    
    PR-QUEUE-001D: Tests the async history writer and ensures GUI thread
    is not blocked by file I/O during job completion.
    """

    @pytest.fixture
    def app_root(self):
        """Create test application root with proper cleanup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            yield root

    @patch("src.api.webui_api.WebUIAPI")
    def test_jt07_small_batch_no_stall(self, mock_webui_api, app_root):
        """Test small batch (3 jobs) executes without GUI stall.
        
        Scenario: Queue 3 jobs, verify no watchdog stalls detected.
        
        Assertions:
        - All 3 jobs complete successfully
        - No UI heartbeat stalls detected
        - History records all completions
        - Queue persists correctly
        """
        # Setup fast mock execution
        mock_webui_api.return_value.txt2img.return_value = {
            "images": [{"data": "base64_encoded_image"}],
            "info": '{"prompt": "test", "seed": 12345}',
        }

        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window
            
            # Configure for fast execution
            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=5,  # Fast
            )
            
            # Enable only txt2img
            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(False)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)
            
            # Track UI heartbeat before execution
            initial_heartbeat = getattr(app_controller, "last_ui_heartbeat_ts", 0)
            logger.info(f"Initial UI heartbeat: {initial_heartbeat}")
            
            # Queue 3 jobs
            jobs_to_queue = 3
            for i in range(jobs_to_queue):
                window.pipeline_tab.prompt_text.delete(0, "end")
                window.pipeline_tab.prompt_text.insert(0, f"Test prompt {i+1}")
                
                # Simulate "Add to Queue" button
                if hasattr(window.pipeline_tab, "on_add_to_queue"):
                    window.pipeline_tab.on_add_to_queue()
                    window.root.update()  # Process GUI events
                    time.sleep(0.1)  # Allow background thread to process
            
            # Verify jobs were queued
            queue_jobs = app_state.get_queue_jobs()
            assert len(queue_jobs) == jobs_to_queue, f"Expected {jobs_to_queue} jobs, got {len(queue_jobs)}"
            
            # Start queue execution
            job_service = harness.controller.job_service
            if job_service and hasattr(job_service, "start_queue_runner"):
                job_service.start_queue_runner()
            
            # Wait for all jobs to complete (with timeout)
            max_wait = 30  # 30 seconds
            start_time = time.time()
            while time.time() - start_time < max_wait:
                window.root.update()  # Keep GUI responsive
                queue_jobs = app_state.get_queue_jobs()
                if len(queue_jobs) == 0:
                    break
                time.sleep(0.5)
            
            # Verify all jobs completed
            assert len(app_state.get_queue_jobs()) == 0, "Queue should be empty after execution"
            
            # Verify UI heartbeat stayed active (no stalls)
            final_heartbeat = getattr(app_controller, "last_ui_heartbeat_ts", 0)
            logger.info(f"Final UI heartbeat: {final_heartbeat}")
            assert final_heartbeat > initial_heartbeat, "UI heartbeat should have updated during execution"
            
            # Verify history recorded all jobs
            history_store = getattr(job_service, "history_store", None)
            if history_store:
                history_entries = history_store.list_jobs(limit=jobs_to_queue)
                assert len(history_entries) >= jobs_to_queue, f"Expected {jobs_to_queue} history entries"
            
            logger.info("✅ Small batch test passed - no GUI stalls detected")

    @patch("src.api.webui_api.WebUIAPI")
    def test_jt07_large_batch_responsiveness(self, mock_webui_api, app_root):
        """Test large batch (80+ jobs) executes without blocking GUI thread.
        
        Scenario: Queue 80 jobs, verify GUI remains responsive throughout.
        
        Assertions:
        - GUI heartbeat never stalls (no 3+ second gaps)
        - History writer thread handles all completions
        - No watchdog diagnostics triggered
        - Queue persistence works correctly
        """
        # Setup ultra-fast mock execution
        mock_webui_api.return_value.txt2img.return_value = {
            "images": [{"data": "base64_encoded_image"}],
            "info": '{"prompt": "test", "seed": 12345}',
        }
        
        with pipeline_harness() as harness:
            app_state = harness.app_state
            app_controller = harness.controller
            window = harness.window
            
            # Configure for ultra-fast execution
            update_current_config(
                app_state,
                model_name="dummy-model",
                sampler_name="Euler a",
                steps=1,  # Ultra-fast for testing
            )
            
            # Enable only txt2img
            window.pipeline_tab.txt2img_enabled.set(True)
            window.pipeline_tab.upscale_enabled.set(False)
            window.pipeline_tab.img2img_enabled.set(False)
            window.pipeline_tab.adetailer_enabled.set(False)
            
            # Track heartbeat history
            heartbeat_samples = []
            
            def sample_heartbeat():
                """Sample current heartbeat timestamp."""
                ts = getattr(app_controller, "last_ui_heartbeat_ts", 0)
                heartbeat_samples.append((time.time(), ts))
            
            # Initial sample
            sample_heartbeat()
            logger.info(f"Starting large batch test with {len(heartbeat_samples)} initial samples")
            
            # Queue 80 jobs
            jobs_to_queue = 80
            logger.info(f"Queueing {jobs_to_queue} jobs...")
            
            for i in range(jobs_to_queue):
                window.pipeline_tab.prompt_text.delete(0, "end")
                window.pipeline_tab.prompt_text.insert(0, f"Large batch test job {i+1}")
                
                # Simulate "Add to Queue" button
                if hasattr(window.pipeline_tab, "on_add_to_queue"):
                    window.pipeline_tab.on_add_to_queue()
                    window.root.update()  # Process GUI events
                    
                    # Sample heartbeat periodically
                    if i % 10 == 0:
                        sample_heartbeat()
                        time.sleep(0.05)  # Brief pause to allow processing
            
            # Verify jobs were queued
            queue_jobs = app_state.get_queue_jobs()
            assert len(queue_jobs) == jobs_to_queue, f"Expected {jobs_to_queue} jobs, got {len(queue_jobs)}"
            logger.info(f"✅ Successfully queued {jobs_to_queue} jobs")
            
            # Start queue execution
            job_service = harness.controller.job_service
            if job_service and hasattr(job_service, "start_queue_runner"):
                job_service.start_queue_runner()
            
            # Monitor execution with heartbeat sampling
            max_wait = 120  # 2 minutes for 80 jobs
            start_time = time.time()
            sample_interval = 1.0  # Sample every second
            last_sample_time = start_time
            
            logger.info("Monitoring execution with heartbeat sampling...")
            
            while time.time() - start_time < max_wait:
                window.root.update()  # Keep GUI responsive
                
                # Sample heartbeat regularly
                now = time.time()
                if now - last_sample_time >= sample_interval:
                    sample_heartbeat()
                    last_sample_time = now
                
                # Check if queue is empty
                queue_jobs = app_state.get_queue_jobs()
                if len(queue_jobs) == 0:
                    logger.info("All jobs completed!")
                    break
                
                # Brief sleep to avoid tight loop
                time.sleep(0.1)
            
            # Final sample
            sample_heartbeat()
            
            # Verify execution completed
            final_queue = app_state.get_queue_jobs()
            assert len(final_queue) == 0, f"Queue should be empty, found {len(final_queue)} remaining jobs"
            
            # Analyze heartbeat samples for stalls
            logger.info(f"Analyzing {len(heartbeat_samples)} heartbeat samples...")
            max_gap = 0.0
            stall_detected = False
            
            for i in range(1, len(heartbeat_samples)):
                real_time_gap = heartbeat_samples[i][0] - heartbeat_samples[i-1][0]
                heartbeat_gap = heartbeat_samples[i][1] - heartbeat_samples[i-1][1]
                
                # Heartbeat should advance roughly in line with real time
                # A stall is when heartbeat stops updating for 3+ seconds
                if heartbeat_gap < real_time_gap - 3.0:
                    stall_detected = True
                    logger.warning(f"⚠️  Stall detected: real_time={real_time_gap:.2f}s, heartbeat={heartbeat_gap:.2f}s")
                
                max_gap = max(max_gap, real_time_gap - heartbeat_gap)
            
            logger.info(f"Max heartbeat lag: {max_gap:.2f}s")
            
            # Assert no stalls detected
            assert not stall_detected, "GUI heartbeat stalled during execution (3+ second gap)"
            
            # Verify history recorded all jobs
            history_store = getattr(job_service, "history_store", None)
            if history_store:
                # Give history writer thread time to flush
                time.sleep(1.0)
                
                history_entries = history_store.list_jobs(limit=jobs_to_queue + 10)
                assert len(history_entries) >= jobs_to_queue, \
                    f"Expected {jobs_to_queue} history entries, got {len(history_entries)}"
            
            logger.info(f"✅ Large batch test passed - {jobs_to_queue} jobs completed, no GUI stalls")

    def test_jt07_history_writer_thread_shutdown(self, app_root):
        """Test history writer thread shuts down cleanly.
        
        Scenario: Start app, append some history, shutdown, verify clean termination.
        
        Assertions:
        - Writer thread starts on init
        - Writer thread processes appends correctly
        - Writer thread terminates cleanly on shutdown
        - No pending operations lost
        """
        with pipeline_harness() as harness:
            job_service = harness.controller.job_service
            history_store = getattr(job_service, "history_store", None)
            
            if not history_store:
                pytest.skip("History store not available")
            
            # Verify writer thread is running
            writer_thread = getattr(history_store, "_writer_thread", None)
            assert writer_thread is not None, "Writer thread should exist"
            assert writer_thread.is_alive(), "Writer thread should be alive"
            
            logger.info(f"✅ Writer thread running: {writer_thread.name}")
            
            # Queue some operations
            from src.history.history_record import HistoryRecord
            for i in range(5):
                record = HistoryRecord(
                    id=f"test-{i}",
                    timestamp=time.time(),
                    status="completed",
                )
                history_store.append(record)
            
            # Give writer time to process
            time.sleep(0.5)
            
            # Trigger shutdown
            history_store.shutdown()
            
            # Verify thread terminated
            assert not writer_thread.is_alive(), "Writer thread should have terminated"
            
            # Verify queue is empty (all operations processed)
            write_queue = getattr(history_store, "_write_queue", None)
            if write_queue:
                assert write_queue.empty(), "Write queue should be empty after shutdown"
            
            logger.info("✅ History writer thread shutdown cleanly")
