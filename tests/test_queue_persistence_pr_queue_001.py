"""
Test suite for PR-QUEUE-001: Queue Persistence Integrity

Validates:
1. Queue state saves/restores without corruption
2. No orphan jobs created on restore
3. Deferred autostart logic properly removed
4. Queue submission handles all preview jobs without arbitrary limits
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from datetime import datetime
from src.controller.job_execution_controller import JobExecutionController
from src.queue.job_model import Job, JobStatus, JobPriority
from src.pipeline.job_models_v2 import NormalizedJobRecord
from src.services.queue_store_v2 import QueueSnapshotV1


@dataclass
class MockQueue:
    """Mock queue that tracks restore calls."""
    jobs: list[Job]
    restore_called: bool = False
    restored_jobs: list[Job] | None = None
    
    def list_jobs(self):
        return self.jobs
    
    def restore_jobs(self, jobs: list[Job]):
        self.restore_called = True
        self.restored_jobs = list(jobs)
        self.jobs.extend(jobs)


class TestQueuePersistenceIntegrity:
    """Verify queue state persistence doesn't corrupt or duplicate jobs."""
    
    def test_restore_does_not_use_deferred_autostart(self):
        """PR-QUEUE-001: Ensure _deferred_autostart logic was fully removed."""
        mock_runner = Mock()
        mock_runner.start = Mock()
        mock_runner.stop = Mock()
        mock_runner.is_running = Mock(return_value=False)
        
        mock_queue = MockQueue(jobs=[])
        
        snapshot = QueueSnapshotV1(
            jobs=[
                {
                    "queue_id": "test-job-1",
                    "njr_snapshot": {
                        "normalized_job": {
                            "job_id": "test-job-1",
                            "positive_prompt": "test",
                            "negative_prompt": "",
                            "base_model": "test_model",
                            "sampler_name": "Euler",
                            "scheduler": "Normal",
                            "steps": 20,
                            "cfg_scale": 7.0,
                            "width": 512,
                            "height": 512,
                            "seed": -1,
                            "batch_index": 0,
                            "batch_total": 1,
                        }
                    },
                    "priority": 1,
                    "status": "queued",
                    "created_at": "2025-12-25T00:00:00",
                    "queue_schema": "2.6",
                    "metadata": {},
                }
            ],
            auto_run_enabled=True,
            paused=False,
        )
        
        with patch("src.controller.job_execution_controller.load_queue_snapshot", return_value=snapshot):
            controller = JobExecutionController(
                runner=mock_runner,
                queue=mock_queue,
                execute_fn=Mock(),
            )
            
            # Verify _deferred_autostart attribute doesn't exist
            assert not hasattr(controller, "_deferred_autostart"), \
                "_deferred_autostart should not exist (removed in PR-CORE1-D22A)"
            
            # Verify jobs were restored
            assert mock_queue.restore_called, "restore_jobs should have been called"
            assert mock_queue.restored_jobs is not None
            assert len(mock_queue.restored_jobs) == 1
    
    def test_restore_handles_empty_snapshot_gracefully(self):
        """Verify empty/missing snapshots don't crash."""
        mock_runner = Mock()
        mock_queue = MockQueue(jobs=[])
        
        with patch("src.controller.job_execution_controller.load_queue_snapshot", return_value=None):
            controller = JobExecutionController(
                runner=mock_runner,
                queue=mock_queue,
                execute_fn=Mock(),
            )
            
            assert not mock_queue.restore_called
            assert len(mock_queue.jobs) == 0
    
    def test_restore_filters_non_queued_jobs(self):
        """Verify only QUEUED jobs are restored (not COMPLETED, FAILED, etc)."""
        mock_runner = Mock()
        mock_queue = MockQueue(jobs=[])
        
        snapshot = QueueSnapshotV1(
            jobs=[
                {
                    "queue_id": "queued-job",
                    "njr_snapshot": {
                        "normalized_job": {
                            "job_id": "queued-job",
                            "positive_prompt": "test",
                            "negative_prompt": "",
                            "base_model": "test_model",
                            "sampler_name": "Euler",
                            "scheduler": "Normal",
                            "steps": 20,
                            "cfg_scale": 7.0,
                            "width": 512,
                            "height": 512,
                            "seed": -1,
                            "batch_index": 0,
                            "batch_total": 1,
                        }
                    },
                    "priority": 1,
                    "status": "queued",
                    "created_at": "2025-12-25T00:00:00",
                    "queue_schema": "2.6",
                    "metadata": {},
                },
                {
                    "queue_id": "completed-job",
                    "njr_snapshot": {
                        "normalized_job": {
                            "job_id": "completed-job",
                            "positive_prompt": "test2",
                            "negative_prompt": "",
                            "base_model": "test_model",
                            "sampler_name": "Euler",
                            "scheduler": "Normal",
                            "steps": 20,
                            "cfg_scale": 7.0,
                            "width": 512,
                            "height": 512,
                            "seed": -1,
                            "batch_index": 0,
                            "batch_total": 1,
                        }
                    },
                    "priority": 1,
                    "status": "completed",  # Should NOT be restored
                    "created_at": "2025-12-25T00:00:00",
                    "queue_schema": "2.6",
                    "metadata": {},
                },
            ],
            auto_run_enabled=False,
            paused=False,
        )
        
        with patch("src.controller.job_execution_controller.load_queue_snapshot", return_value=snapshot):
            controller = JobExecutionController(
                runner=mock_runner,
                queue=mock_queue,
                execute_fn=Mock(),
            )
            
            # Only queued job should be restored
            assert mock_queue.restore_called
            assert mock_queue.restored_jobs is not None
            assert len(mock_queue.restored_jobs) == 1
            assert mock_queue.restored_jobs[0].job_id == "queued-job"


class TestQueueSubmissionLimits:
    """Verify there are no arbitrary limits on queue submission."""
    
    def test_submit_large_batch_of_jobs(self):
        """Verify submitting >10 jobs doesn't hit hidden limits."""
        from src.controller.pipeline_controller import PipelineController
        from src.models.pack_job_entry import PackJobEntry
        
        # Create 20 mock NormalizedJobRecords
        records = []
        for i in range(20):
            njr = NormalizedJobRecord(
                job_id=f"job-{i}",
                positive_prompt=f"test prompt {i}",
                negative_prompt="",
                base_model="test_model",
                sampler_name="Euler",
                scheduler="Normal",
                steps=20,
                cfg_scale=7.0,
                width=512,
                height=512,
                seed=-1,
                batch_index=0,
                batch_total=1,
                prompt_pack_id="test_pack",
            )
            records.append(njr)
        
        mock_job_service = Mock()
        mock_job_service.submit_job_with_run_mode = Mock()
        mock_job_service.auto_run_enabled = False
        mock_job_service._batch_mode = False
        
        controller = PipelineController(
            app_state=Mock(),
            config_manager=Mock(),
            webui_connection=Mock(),
            job_service=mock_job_service,
        )
        
        # Submit all 20 jobs
        submitted = controller.submit_preview_jobs_to_queue(records=records)
        
        # All 20 should be submitted (no arbitrary limit like 3)
        assert submitted == 20, f"Expected 20 jobs submitted, got {submitted}"
        assert mock_job_service.submit_job_with_run_mode.call_count == 20


class TestQueueSubmissionErrorHandling:
    """Verify queue operations handle errors gracefully without crashing GUI."""
    
    def test_enqueue_handles_none_controller_gracefully(self):
        """Verify enqueue doesn't crash if pipeline_controller is None."""
        from src.controller.app_controller import AppController
        
        controller = AppController()
        controller.pipeline_controller = None
        controller._append_log = Mock()
        controller._queue_submit_in_progress = False
        
        # Should not crash
        controller._enqueue_draft_jobs_async()
        
        # Should log error
        controller._append_log.assert_called()
        error_logs = [call[0][0] for call in controller._append_log.call_args_list if "ERROR" in call[0][0]]
        assert len(error_logs) > 0, "Should have logged an ERROR message"
    
    def test_enqueue_logs_traceback_on_exception(self):
        """Verify full traceback is captured when queue submission fails."""
        from src.controller.app_controller import AppController
        
        controller = AppController()
        mock_pipeline = Mock()
        mock_pipeline.get_preview_jobs = Mock(side_effect=RuntimeError("Test error"))
        controller.pipeline_controller = mock_pipeline
        controller._append_log = Mock()
        controller._queue_submit_in_progress = False
        
        # Should not crash
        controller._enqueue_draft_jobs_async()
        
        # Should log full traceback
        log_calls = [call[0][0] for call in controller._append_log.call_args_list]
        assert any("Traceback" in log for log in log_calls), "Should have logged traceback"
        assert any("Test error" in log for log in log_calls), "Should have logged error message"
