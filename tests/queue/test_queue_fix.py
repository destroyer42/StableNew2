"""Tests for AppState queue-job notification behavior."""

from dataclasses import replace
from datetime import datetime
from src.gui.app_state_v2 import AppStateV2
from src.pipeline.job_models_v2 import UnifiedJobSummary


def create_test_job(job_id: str, prompt: str) -> UnifiedJobSummary:
    """Create a minimal test job summary."""
    return UnifiedJobSummary(
        job_id=job_id,
        prompt_pack_id="test-pack",
        prompt_pack_name="Test Pack",
        prompt_pack_row_index=0,
        positive_prompt_preview=prompt,
        negative_prompt_preview=None,
        lora_preview="",
        embedding_preview="",
        base_model="test-model.safetensors",
        sampler_name="DPM++ 2M",
        cfg_scale=7.0,
        steps=20,
        width=512,
        height=512,
        stage_chain_labels=["txt2img"],
        randomization_enabled=False,
        matrix_mode=None,
        matrix_slot_values_preview="",
        variant_index=0,
        batch_index=0,
        config_variant_label="default",
        config_variant_index=0,
        estimated_image_count=1,
        status="queued",
        created_at=datetime.now(),
        completed_at=None,
    )


def test_queue_jobs_change_detection() -> None:
    """Test that set_queue_jobs properly detects changes when jobs are removed."""

    # Create an app_state
    app_state = AppStateV2()

    # Track notifications
    notifications: list[str] = []
    app_state.subscribe("queue_jobs", lambda: notifications.append("queue_jobs_changed"))

    # Create test job summaries
    job1 = create_test_job("job-1", "Test job 1")
    job2 = create_test_job("job-2", "Test job 2")

    # Set initial jobs
    app_state.set_queue_jobs([job1, job2])
    assert len(notifications) == 1, "Should notify after initial set"
    assert len(app_state.queue_jobs) == 2, "Should have 2 jobs"

    # Remove one job (simulate queue.remove())
    app_state.set_queue_jobs([job2])
    assert len(notifications) == 2, "Should notify after removal"
    assert len(app_state.queue_jobs) == 1, "Should have 1 job remaining"
    assert app_state.queue_jobs[0].job_id == "job-2", "Should have correct job remaining"

    # Remove all jobs
    app_state.set_queue_jobs([])
    assert len(notifications) == 3, "Should notify after clearing"
    assert len(app_state.queue_jobs) == 0, "Should have no jobs"

    print("[OK] All queue change detection tests passed!")


def test_queue_jobs_no_duplicate_notifications() -> None:
    """Test that setting the same jobs doesn't trigger unnecessary notifications."""

    app_state = AppStateV2()

    notifications: list[str] = []
    app_state.subscribe("queue_jobs", lambda: notifications.append("notified"))

    job1 = create_test_job("job-1", "Test")

    # Set jobs twice with same content
    app_state.set_queue_jobs([job1])
    assert len(notifications) == 1

    app_state.set_queue_jobs([job1])
    # Should NOT notify again since job_id is the same
    assert len(notifications) == 1, "Should not notify when jobs haven't changed"

    print("[OK] No duplicate notifications test passed!")


def test_queue_jobs_notify_when_same_job_changes_visible_queue_state() -> None:
    """Same queue IDs should still notify when the rendered queue row changes."""

    app_state = AppStateV2()

    notifications: list[str] = []
    app_state.subscribe("queue_jobs", lambda: notifications.append("notified"))

    queued_job = create_test_job("job-1", "Test")
    running_job = replace(queued_job, status="RUNNING")

    app_state.set_queue_jobs([queued_job])
    app_state.set_queue_jobs([running_job])

    assert len(notifications) == 2, "Should notify when queue row content changes for same job ID"


if __name__ == "__main__":
    test_queue_jobs_change_detection()
    test_queue_jobs_no_duplicate_notifications()
    print("\n[OK] All tests passed! Queue remove button fix is working correctly.")
