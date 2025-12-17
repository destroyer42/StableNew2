"""Tests for QueuePanelV2.set_normalized_jobs() with NormalizedJobRecord (PR-CORE1-A3).

Confirms queue panel uses NJR-based display, not pipeline_config.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord, QueueJobV2

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tk_root():
    """Provide a Tk root window or skip if Tk/Tcl is unavailable."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def queue_panel(tk_root):
    """Create a QueuePanelV2 instance."""
    from src.gui.panels_v2.queue_panel_v2 import QueuePanelV2

    panel = QueuePanelV2(tk_root)
    panel.pack(fill=tk.BOTH, expand=True)
    tk_root.update_idletasks()
    return panel


def make_job(
    job_id: str = "job-1",
    model: str = "sd_xl_base_1.0",
    prompt: str = "test prompt",
    seed: int = 12345,
    variant_index: int = 0,
    variant_total: int = 1,
    batch_index: int = 0,
    batch_total: int = 1,
    stages: list[str] | None = None,
) -> NormalizedJobRecord:
    """Create a NormalizedJobRecord for testing."""
    config = {
        "model": model,
        "prompt": prompt,
        "steps": 20,
        "cfg_scale": 7.0,
        "stages": stages or ["txt2img"],
    }
    return NormalizedJobRecord(
        job_id=job_id,
        config=config,
        path_output_dir="output",
        filename_template="{seed}",
        seed=seed,
        variant_index=variant_index,
        variant_total=variant_total,
        batch_index=batch_index,
        batch_total=batch_total,
    )


# ---------------------------------------------------------------------------
# Tests for set_normalized_jobs()
# ---------------------------------------------------------------------------


class TestQueuePanelSetNormalizedJobs:
    """Tests for QueuePanelV2.set_normalized_jobs() method."""

    def test_set_normalized_jobs_empty_list(self, queue_panel):
        """set_normalized_jobs() with empty list clears queue."""
        queue_panel.set_normalized_jobs([])

        assert len(queue_panel._jobs) == 0
        assert queue_panel.count_label.cget("text") == "(0 jobs)"

    def test_set_normalized_jobs_single_job(self, queue_panel):
        """set_normalized_jobs() with single job populates queue."""
        job = make_job(job_id="test-job-1")
        queue_panel.set_normalized_jobs([job])

        assert len(queue_panel._jobs) == 1
        assert queue_panel._jobs[0].job_id == "test-job-1"
        assert queue_panel.count_label.cget("text") == "(1 job)"

    def test_set_normalized_jobs_multiple_jobs(self, queue_panel):
        """set_normalized_jobs() with multiple jobs populates queue."""
        jobs = [make_job(job_id=f"job-{i}") for i in range(5)]
        queue_panel.set_normalized_jobs(jobs)

        assert len(queue_panel._jobs) == 5
        assert queue_panel.count_label.cget("text") == "(5 jobs)"

    def test_set_normalized_jobs_preserves_job_id(self, queue_panel):
        """set_normalized_jobs() preserves job_id from NormalizedJobRecord."""
        job = make_job(job_id="preserved-id-123")
        queue_panel.set_normalized_jobs([job])

        assert queue_panel._jobs[0].job_id == "preserved-id-123"

    def test_set_normalized_jobs_creates_queue_job_v2(self, queue_panel):
        """set_normalized_jobs() creates QueueJobV2 instances."""
        job = make_job()
        queue_panel.set_normalized_jobs([job])

        assert isinstance(queue_panel._jobs[0], QueueJobV2)

    def test_set_normalized_jobs_snapshot_contains_model(self, queue_panel):
        """set_normalized_jobs() creates snapshot with model."""
        job = make_job(model="test_model_xyz")
        queue_panel.set_normalized_jobs([job])

        snapshot = queue_panel._jobs[0].config_snapshot
        assert snapshot.get("model") == "test_model_xyz"

    def test_set_normalized_jobs_snapshot_contains_seed(self, queue_panel):
        """set_normalized_jobs() creates snapshot with seed."""
        job = make_job(seed=99999)
        queue_panel.set_normalized_jobs([job])

        snapshot = queue_panel._jobs[0].config_snapshot
        assert snapshot.get("seed") == 99999

    def test_set_normalized_jobs_snapshot_contains_prompt(self, queue_panel):
        """set_normalized_jobs() creates snapshot with prompt."""
        job = make_job(prompt="unique test prompt")
        queue_panel.set_normalized_jobs([job])

        snapshot = queue_panel._jobs[0].config_snapshot
        assert snapshot.get("prompt") == "unique test prompt"

    def test_set_normalized_jobs_metadata_has_variant_info(self, queue_panel):
        """set_normalized_jobs() stores variant info in metadata."""
        job = make_job(variant_index=2, variant_total=5)
        queue_panel.set_normalized_jobs([job])

        metadata = queue_panel._jobs[0].metadata
        assert metadata.get("variant_index") == 2
        assert metadata.get("variant_total") == 5

    def test_set_normalized_jobs_metadata_has_batch_info(self, queue_panel):
        """set_normalized_jobs() stores batch info in metadata."""
        job = make_job(batch_index=1, batch_total=3)
        queue_panel.set_normalized_jobs([job])

        metadata = queue_panel._jobs[0].metadata
        assert metadata.get("batch_index") == 1
        assert metadata.get("batch_total") == 3

    def test_set_normalized_jobs_updates_listbox(self, queue_panel):
        """set_normalized_jobs() updates the listbox display."""
        jobs = [make_job(job_id="j1"), make_job(job_id="j2")]
        queue_panel.set_normalized_jobs(jobs)

        listbox_size = queue_panel.job_listbox.size()
        assert listbox_size == 2

    def test_set_normalized_jobs_listbox_shows_summary(self, queue_panel):
        """set_normalized_jobs() shows job summary in listbox."""
        job = make_job(model="my_model", seed=12345)
        queue_panel.set_normalized_jobs([job])

        # Get first listbox item
        item_text = queue_panel.job_listbox.get(0)
        assert "my_model" in item_text or "12345" in item_text


# ---------------------------------------------------------------------------
# Tests for conversion correctness
# ---------------------------------------------------------------------------


class TestNormalizedJobToQueueJobConversion:
    """Tests for NormalizedJobRecord to QueueJobV2 conversion."""

    def test_conversion_handles_none_seed(self, queue_panel):
        """Conversion handles None seed correctly."""
        job = make_job()
        job.seed = None
        queue_panel.set_normalized_jobs([job])

        snapshot = queue_panel._jobs[0].config_snapshot
        assert snapshot.get("seed") is None

    def test_conversion_handles_output_dir(self, queue_panel):
        """Conversion includes output_dir in snapshot."""
        job = NormalizedJobRecord(
            job_id="test-id",
            config={"model": "test"},
            path_output_dir="/path/to/output",
            filename_template="{seed}",
        )
        queue_panel.set_normalized_jobs([job])

        snapshot = queue_panel._jobs[0].config_snapshot
        assert snapshot.get("output_dir") == "/path/to/output"

    def test_conversion_handles_filename_template(self, queue_panel):
        """Conversion includes filename_template in snapshot."""
        job = NormalizedJobRecord(
            job_id="test-id",
            config={"model": "test"},
            path_output_dir="output",
            filename_template="{model}_{seed}",
        )
        queue_panel.set_normalized_jobs([job])

        snapshot = queue_panel._jobs[0].config_snapshot
        assert snapshot.get("filename_template") == "{model}_{seed}"


# ---------------------------------------------------------------------------
# Tests for repeated updates
# ---------------------------------------------------------------------------


class TestQueuePanelUpdateCycle:
    """Tests for repeated updates to queue panel."""

    def test_set_normalized_jobs_can_be_called_multiple_times(self, queue_panel):
        """set_normalized_jobs() can be called multiple times."""
        jobs1 = [make_job(job_id="j1")]
        jobs2 = [make_job(job_id="j2"), make_job(job_id="j3")]

        queue_panel.set_normalized_jobs(jobs1)
        assert len(queue_panel._jobs) == 1

        queue_panel.set_normalized_jobs(jobs2)
        assert len(queue_panel._jobs) == 2

    def test_set_normalized_jobs_replaces_previous(self, queue_panel):
        """set_normalized_jobs() replaces previous jobs entirely."""
        jobs1 = [make_job(job_id=f"first-{i}") for i in range(3)]
        jobs2 = [make_job(job_id=f"second-{i}") for i in range(2)]

        queue_panel.set_normalized_jobs(jobs1)
        queue_panel.set_normalized_jobs(jobs2)

        # Check only second batch is present
        job_ids = [j.job_id for j in queue_panel._jobs]
        assert "second-0" in job_ids
        assert "second-1" in job_ids
        assert "first-0" not in job_ids

    def test_set_normalized_jobs_then_empty(self, queue_panel):
        """set_normalized_jobs() followed by empty list clears queue."""
        jobs = [make_job()]
        queue_panel.set_normalized_jobs(jobs)
        assert len(queue_panel._jobs) == 1

        queue_panel.set_normalized_jobs([])
        assert len(queue_panel._jobs) == 0


# ---------------------------------------------------------------------------
# Tests for integration with update_jobs
# ---------------------------------------------------------------------------


class TestQueuePanelIntegration:
    """Tests for QueuePanelV2 integration between methods."""

    def test_set_normalized_jobs_uses_update_jobs(self, queue_panel):
        """set_normalized_jobs() internally uses update_jobs()."""
        job = make_job()
        queue_panel.set_normalized_jobs([job])

        # Verify update_jobs was effectively called (internal state matches)
        assert len(queue_panel._jobs) == 1
        assert queue_panel.job_listbox.size() == 1

    def test_button_states_after_set_normalized_jobs(self, queue_panel):
        """Button states are correct after set_normalized_jobs()."""
        # Initially no jobs, clear should be disabled
        queue_panel.set_normalized_jobs([])
        # Clear button disabled when no jobs
        clear_state = queue_panel.clear_button.state()
        assert "disabled" in clear_state

        # Add jobs, clear should be enabled
        queue_panel.set_normalized_jobs([make_job()])
        clear_state_after = queue_panel.clear_button.state()
        assert "disabled" not in clear_state_after
