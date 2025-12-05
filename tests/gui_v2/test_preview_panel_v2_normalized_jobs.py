"""Tests for PreviewPanelV2.set_jobs() with NormalizedJobRecord."""

from __future__ import annotations

import tkinter as tk

import pytest

from src.pipeline.job_models_v2 import JobUiSummary, NormalizedJobRecord


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
def preview_panel(tk_root):
    """Create a PreviewPanelV2 instance."""
    from src.gui.preview_panel_v2 import PreviewPanelV2
    panel = PreviewPanelV2(tk_root)
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
# Tests for JobUiSummary dataclass
# ---------------------------------------------------------------------------


class TestJobUiSummary:
    """Tests for JobUiSummary dataclass."""

    def test_job_ui_summary_has_expected_fields(self):
        """JobUiSummary has all required display fields."""
        summary = JobUiSummary(
            job_id="test-id",
            model="sd_xl_base_1.0",
            prompt_short="test prompt",
            seed_display="12345",
            variant_label="[v1/2]",
            batch_label="[b1/3]",
            stages_summary="txt2img → upscale",
            output_dir="output",
            total_summary="sd_xl_base_1.0 | seed=12345 [v1/2] [b1/3]",
        )
        assert summary.job_id == "test-id"
        assert summary.model == "sd_xl_base_1.0"
        assert summary.prompt_short == "test prompt"
        assert summary.seed_display == "12345"
        assert summary.variant_label == "[v1/2]"
        assert summary.batch_label == "[b1/3]"
        assert summary.stages_summary == "txt2img → upscale"
        assert summary.output_dir == "output"
        assert summary.total_summary == "sd_xl_base_1.0 | seed=12345 [v1/2] [b1/3]"


# ---------------------------------------------------------------------------
# Tests for NormalizedJobRecord.to_ui_summary()
# ---------------------------------------------------------------------------


class TestNormalizedJobRecordToUiSummary:
    """Tests for NormalizedJobRecord.to_ui_summary() method."""

    def test_to_ui_summary_basic(self):
        """to_ui_summary() returns JobUiSummary with correct fields."""
        job = make_job()
        summary = job.to_ui_summary()

        assert isinstance(summary, JobUiSummary)
        assert summary.job_id == "job-1"
        assert summary.model == "sd_xl_base_1.0"
        assert summary.seed_display == "12345"

    def test_to_ui_summary_variant_label(self):
        """to_ui_summary() includes variant label when variant_total > 1."""
        job = make_job(variant_index=0, variant_total=3)
        summary = job.to_ui_summary()

        assert summary.variant_label == "[v1/3]"

    def test_to_ui_summary_batch_label(self):
        """to_ui_summary() includes batch label when batch_total > 1."""
        job = make_job(batch_index=1, batch_total=5)
        summary = job.to_ui_summary()

        assert summary.batch_label == "[b2/5]"

    def test_to_ui_summary_no_labels_for_single(self):
        """to_ui_summary() has empty labels for single variant/batch."""
        job = make_job(variant_total=1, batch_total=1)
        summary = job.to_ui_summary()

        assert summary.variant_label == ""
        assert summary.batch_label == ""

    def test_to_ui_summary_stages_from_config(self):
        """to_ui_summary() extracts stages from config."""
        job = make_job(stages=["txt2img", "upscale"])
        summary = job.to_ui_summary()

        assert summary.stages_summary == "txt2img → upscale"

    def test_to_ui_summary_stages_with_adetailer(self):
        """to_ui_summary() maps adetailer to ADetailer."""
        job = make_job(stages=["txt2img", "adetailer"])
        summary = job.to_ui_summary()

        assert summary.stages_summary == "txt2img → ADetailer"

    def test_to_ui_summary_prompt_truncation(self):
        """to_ui_summary() truncates long prompts at 40 chars."""
        long_prompt = "A" * 50
        job = make_job(prompt=long_prompt)
        summary = job.to_ui_summary()

        assert len(summary.prompt_short) == 43  # 40 chars + "..."
        assert summary.prompt_short.endswith("...")

    def test_to_ui_summary_none_seed(self):
        """to_ui_summary() shows ? for None seed."""
        job = make_job()
        job.seed = None
        summary = job.to_ui_summary()

        assert summary.seed_display == "?"

    def test_to_ui_summary_total_summary_format(self):
        """to_ui_summary() formats total_summary correctly."""
        job = make_job(variant_index=1, variant_total=2, batch_index=0, batch_total=3)
        summary = job.to_ui_summary()

        assert "sd_xl_base_1.0" in summary.total_summary
        assert "seed=12345" in summary.total_summary
        assert "[v2/2]" in summary.total_summary
        assert "[b1/3]" in summary.total_summary


# ---------------------------------------------------------------------------
# Tests for PreviewPanelV2.set_jobs()
# ---------------------------------------------------------------------------


class TestPreviewPanelSetJobs:
    """Tests for PreviewPanelV2.set_jobs() method."""

    def test_set_jobs_empty_list(self, preview_panel):
        """set_jobs() with empty list shows 0 jobs."""
        preview_panel.set_jobs([])

        assert "0" in preview_panel.summary_label.cget("text")

    def test_set_jobs_single_job(self, preview_panel):
        """set_jobs() with single job updates labels."""
        job = make_job()
        preview_panel.set_jobs([job])

        assert "1" in preview_panel.summary_label.cget("text")

    def test_set_jobs_multiple_jobs(self, preview_panel):
        """set_jobs() with multiple jobs shows count."""
        jobs = [make_job(job_id=f"job-{i}") for i in range(5)]
        preview_panel.set_jobs(jobs)

        assert "5" in preview_panel.summary_label.cget("text")

    def test_set_jobs_shows_stages(self, preview_panel):
        """set_jobs() displays stages from first job."""
        job = make_job(stages=["txt2img", "upscale"])
        preview_panel.set_jobs([job])

        mode_text = preview_panel.mode_label.cget("text")
        assert "txt2img" in mode_text
        assert "upscale" in mode_text

    def test_set_jobs_shows_model(self, preview_panel):
        """set_jobs() displays model when single model."""
        jobs = [make_job(model="test_model")]
        preview_panel.set_jobs(jobs)

        jobs_text = preview_panel.jobs_label.cget("text")
        assert "test_model" in jobs_text

    def test_set_jobs_multiple_models(self, preview_panel):
        """set_jobs() shows count when multiple models."""
        jobs = [
            make_job(job_id="j1", model="model_a"),
            make_job(job_id="j2", model="model_b"),
        ]
        preview_panel.set_jobs(jobs)

        jobs_text = preview_panel.jobs_label.cget("text")
        assert "2 different" in jobs_text

    def test_set_jobs_updates_queue_items(self, preview_panel):
        """set_jobs() updates queue items text."""
        jobs = [make_job(job_id="job-1", seed=111), make_job(job_id="job-2", seed=222)]
        preview_panel.set_jobs(jobs)

        # Get queue items text content
        preview_panel.queue_items_text.config(state="normal")
        content = preview_panel.queue_items_text.get("1.0", "end-1c")
        preview_panel.queue_items_text.config(state="disabled")

        assert "111" in content or "222" in content

    def test_set_jobs_truncates_long_lists(self, preview_panel):
        """set_jobs() shows first 10 and '... more' for long lists."""
        jobs = [make_job(job_id=f"job-{i}") for i in range(15)]
        preview_panel.set_jobs(jobs)

        preview_panel.queue_items_text.config(state="normal")
        content = preview_panel.queue_items_text.get("1.0", "end-1c")
        preview_panel.queue_items_text.config(state="disabled")

        assert "5 more" in content

    def test_set_jobs_shows_variant_info(self, preview_panel):
        """set_jobs() shows variant info in scope label."""
        jobs = [
            make_job(job_id="j1", variant_index=0, variant_total=2),
            make_job(job_id="j2", variant_index=1, variant_total=2),
        ]
        preview_panel.set_jobs(jobs)

        scope_text = preview_panel.scope_label.cget("text")
        assert "variant" in scope_text.lower() or "single" in scope_text.lower()


# ---------------------------------------------------------------------------
# Tests for panel update cycle
# ---------------------------------------------------------------------------


class TestPreviewPanelUpdateCycle:
    """Tests for repeated updates to preview panel."""

    def test_set_jobs_can_be_called_multiple_times(self, preview_panel):
        """set_jobs() can be called multiple times without errors."""
        jobs1 = [make_job(job_id="j1")]
        jobs2 = [make_job(job_id="j2"), make_job(job_id="j3")]

        preview_panel.set_jobs(jobs1)
        assert "1" in preview_panel.summary_label.cget("text")

        preview_panel.set_jobs(jobs2)
        assert "2" in preview_panel.summary_label.cget("text")

    def test_set_jobs_then_clear(self, preview_panel):
        """set_jobs() followed by empty list clears display."""
        jobs = [make_job()]
        preview_panel.set_jobs(jobs)
        assert "1" in preview_panel.summary_label.cget("text")

        preview_panel.set_jobs([])
        assert "0" in preview_panel.summary_label.cget("text")
