"""Test to reproduce the queue Remove button bug."""

import tkinter as tk
from unittest.mock import Mock, MagicMock, patch
from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2
from src.pipeline.job_models_v2 import UnifiedJobSummary


def test_queue_remove_updates_gui():
    """Reproduce the bug where Remove button doesn't update the GUI."""
    
    # Create a root window
    root = tk.Tk()
    
    try:
        # Create mock app_state with subscribe capability
        app_state = Mock()
        app_state.queue_jobs = []
        
        # Track subscription callbacks
        subscribers = {}
        def mock_subscribe(key, callback):
            if key not in subscribers:
                subscribers[key] = []
            subscribers[key].append(callback)
        
        app_state.subscribe = mock_subscribe
        
        # Create mock controller
        controller = Mock()
        
        # Track if set_queue_jobs was called
        set_queue_jobs_calls = []
        def mock_set_queue_jobs(jobs):
            set_queue_jobs_calls.append(jobs)
            app_state.queue_jobs = jobs
            # Simulate notification to subscribers
            for callback in subscribers.get("queue_jobs", []):
                callback()
        
        app_state.set_queue_jobs = mock_set_queue_jobs
        
        # Create the queue panel
        panel = QueuePanelV2(root, controller=controller, app_state=app_state)
        
        # Create test jobs
        job1 = Mock(spec=UnifiedJobSummary)
        job1.job_id = "job-1"
        job1.positive_prompt_preview = "Test job 1"
        job1.get_display_summary = Mock(return_value="Test job 1")
        job1.is_running = False
        job1.status = "queued"
        job1.stage = "queued"
        job1.expected_images = 1
        job1.base_params = {}
        
        job2 = Mock(spec=UnifiedJobSummary)
        job2.job_id = "job-2"
        job2.positive_prompt_preview = "Test job 2"
        job2.get_display_summary = Mock(return_value="Test job 2")
        job2.is_running = False
        job2.status = "queued"
        job2.stage = "queued"
        job2.expected_images = 1
        job2.base_params = {}
        
        # Add jobs to the panel
        panel.update_jobs([job1, job2])
        panel.update()
        
        print(f"Initial queue size: {panel.job_listbox.size()}")
        assert panel.job_listbox.size() == 2, "Should have 2 jobs"
        
        # Select the first job
        panel.job_listbox.selection_set(0)
        panel.update()
        
        # Mock the controller's remove method to simulate queue removal
        def mock_remove(job_id):
            print(f"Removing job: {job_id}")
            # Simulate what should happen in the real system
            # After removal, the queue should update and notify listeners
            remaining_jobs = [job2]  # job1 was removed
            app_state.set_queue_jobs(remaining_jobs)
            
        controller.on_queue_remove_job_v2 = mock_remove
        
        # Click the remove button
        panel._on_remove()
        panel.update()
        
        print(f"Queue size after remove: {panel.job_listbox.size()}")
        print(f"set_queue_jobs calls: {len(set_queue_jobs_calls)}")
        print(f"Jobs in last call: {set_queue_jobs_calls[-1] if set_queue_jobs_calls else 'none'}")
        
        # The bug: The GUI should show 1 job, but it might still show 2
        assert panel.job_listbox.size() == 1, f"Should have 1 job after removal, but has {panel.job_listbox.size()}"
        
        print("✅ Test passed - Remove button works correctly!")
        
    finally:
        root.destroy()


if __name__ == "__main__":
    test_queue_remove_updates_gui()
