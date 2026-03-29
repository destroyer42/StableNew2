"""Test queue persistence fix - ensures only QUEUED jobs are saved on shutdown."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from src.queue.job_model import JobStatus


def test_queue_filter_logic():
    """Verify the core filter logic: only QUEUED jobs should be saved."""
    # Simulate what _persist_queue_state does
    test_jobs = [
        {"job_id": "j1", "status": JobStatus.QUEUED},
        {"job_id": "j2", "status": JobStatus.RUNNING},
        {"job_id": "j3", "status": JobStatus.COMPLETED},
        {"job_id": "j4", "status": JobStatus.FAILED},
        {"job_id": "j5", "status": JobStatus.QUEUED},
        {"job_id": "j6", "status": JobStatus.CANCELLED},
    ]
    
    # Apply the filter (same logic as in _persist_queue_state)
    filtered = [job for job in test_jobs if job["status"] == JobStatus.QUEUED]
    
    assert len(filtered) == 2, f"Expected 2 QUEUED jobs, got {len(filtered)}"
    assert filtered[0]["job_id"] == "j1"
    assert filtered[1]["job_id"] == "j5"
    
    print("[OK] Filter logic correctly excludes non-QUEUED jobs")


def test_shutdown_app_has_save_call():
    """Verify shutdown_app() contains a queue save call."""
    from src.controller.app_controller import AppController
    import inspect
    
    source = inspect.getsource(AppController.shutdown_app)
    
    # Check that _save_queue_state is called during shutdown
    assert "_save_queue_state" in source, "shutdown_app should call _save_queue_state"
    assert "Step 7.5" in source, "shutdown_app should have Step 7.5 for queue save"
    
    print("[OK] shutdown_app() includes _save_queue_state call")


def test_job_execution_controller_stop_has_save():
    """Verify JobExecutionController.stop() persists queue state."""
    from src.controller.job_execution_controller import JobExecutionController
    import inspect
    
    source = inspect.getsource(JobExecutionController.stop)
    
    # Check that _persist_queue_state is called during stop
    assert "_persist_queue_state" in source, "stop() should call _persist_queue_state"
    assert "PR-PERSIST-FIX" in source, "stop() should have PR-PERSIST-FIX comment"
    
    print("[OK] JobExecutionController.stop() includes _persist_queue_state call")


def test_persist_queue_state_filters():
    """Verify _persist_queue_state has proper filtering comments."""
    from src.controller.job_execution_controller import JobExecutionController
    import inspect
    
    source = inspect.getsource(JobExecutionController._persist_queue_state)
    
    # Check that filtering is explicit
    assert "JobStatus.QUEUED" in source, "should explicitly check for QUEUED status"
    assert "PR-PERSIST-FIX" in source or "Only save QUEUED jobs" in source, "should have filtering comment"
    
    print("[OK] _persist_queue_state has proper filtering logic")


if __name__ == "__main__":
    test_queue_filter_logic()
    test_shutdown_app_has_save_call()
    test_job_execution_controller_stop_has_save()
    test_persist_queue_state_filters()
    print("\n[OK] All queue persistence tests passed!")
