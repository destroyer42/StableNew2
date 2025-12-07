"""Tests for PreviewPanelV2 job-centric summary rendering (PR-GUI-G)."""

from __future__ import annotations

import tkinter as tk
import pytest

from src.pipeline.job_models_v2 import JobUiSummary


@pytest.fixture
def tk_root():
    """Create a Tk root window or skip if the toolkit is unavailable."""
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError as exc:
        pytest.skip(f"Tkinter/Tcl not available: {exc}")
        return
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def preview_panel(tk_root):
    """Return a PreviewPanelV2 instance for testing."""
    from src.gui.preview_panel_v2 import PreviewPanelV2

    panel = PreviewPanelV2(tk_root)
    panel.pack()
    tk_root.update_idletasks()
    return panel


def make_ui_summary(
    *,
    job_id: str = "job-1",
    model: str = "sd_xl_base_1.0",
    prompt_short: str = "test prompt",
    negative_prompt_short: str | None = None,
    sampler: str = "Euler a",
    steps: int = 25,
    cfg_scale: float = 7.0,
    seed_display: str = "12345",
    variant_label: str = "",
    batch_label: str = "",
    stages_summary: str = "txt2img",
    randomizer_summary: str | None = None,
    has_refiner: bool = False,
    has_hires: bool = False,
    has_upscale: bool = False,
) -> JobUiSummary:
    """Build a minimal JobUiSummary for testing."""
    return JobUiSummary(
        job_id=job_id,
        model=model,
        prompt_short=prompt_short,
        negative_prompt_short=negative_prompt_short,
        sampler=sampler,
        steps=steps,
        cfg_scale=cfg_scale,
        seed_display=seed_display,
        variant_label=variant_label,
        batch_label=batch_label,
        stages_summary=stages_summary,
        randomizer_summary=randomizer_summary,
        has_refiner=has_refiner,
        has_hires=has_hires,
        has_upscale=has_upscale,
        output_dir="output",
        total_summary=f"{model} | seed={seed_display}",
    )


class TestPreviewPanelSummary:
    """JobUiSummary rendering for PreviewPanelV2."""

    def test_renders_job_count(self, preview_panel):
        summaries = [make_ui_summary(job_id=f"job-{i}") for i in range(3)]
        preview_panel.set_job_summaries(summaries)

        assert "Jobs: 3" in preview_panel.job_count_label.cget("text")

    def test_renders_prompt(self, preview_panel):
        summary = make_ui_summary(prompt_short="A beautiful sunset")
        preview_panel.set_job_summaries([summary])

        text = preview_panel.prompt_text.get("1.0", "end").strip()
        assert "beautiful sunset" in text

    def test_renders_negative_prompt(self, preview_panel):
        summary = make_ui_summary(negative_prompt_short="bad quality, blurry")
        preview_panel.set_job_summaries([summary])

        text = preview_panel.negative_prompt_text.get("1.0", "end").strip()
        assert "bad quality" in text

    def test_renders_model_and_sampler(self, preview_panel):
        summary = make_ui_summary(model="realisticVision_v51", sampler="DPM++ 2M Karras")
        preview_panel.set_job_summaries([summary])

        assert "realisticVision_v51" in preview_panel.model_label.cget("text")
        assert "DPM++ 2M Karras" in preview_panel.sampler_label.cget("text")

    def test_renders_settings(self, preview_panel):
        summary = make_ui_summary(steps=30, cfg_scale=8.5, seed_display="99999")
        preview_panel.set_job_summaries([summary])

        assert "30" in preview_panel.steps_label.cget("text")
        assert "8.5" in preview_panel.cfg_label.cget("text")
        assert "99999" in preview_panel.seed_label.cget("text")

    def test_renders_stages(self, preview_panel):
        summary = make_ui_summary(stages_summary="txt2img ƒ+' upscale")
        preview_panel.set_job_summaries([summary])

        assert "txt2img" in preview_panel.stage_summary_label.cget("text")

    def test_clears_when_no_summaries(self, preview_panel):
        preview_panel.set_job_summaries([make_ui_summary()])
        preview_panel.set_job_summaries([])

        assert preview_panel.job_count_label.cget("text") == "No job selected"
        assert preview_panel.prompt_text.get("1.0", "end").strip() == ""

    def test_stage_flags_display(self, preview_panel):
        summary = make_ui_summary(has_refiner=True, has_hires=False, has_upscale=True)
        preview_panel.set_job_summaries([summary])

        flags = preview_panel.stage_flags_label.cget("text")
        assert "Refiner: ON" in flags
        assert "HiRes: OFF" in flags
        assert "Upscale: ON" in flags

    def test_randomizer_summary(self, preview_panel):
        summary = make_ui_summary(randomizer_summary="2 variants × 3 models")
        preview_panel.set_job_summaries([summary])

        assert "2 variants" in preview_panel.randomizer_label.cget("text")

    def test_learning_metadata_placeholder(self, preview_panel):
        summary = make_ui_summary()
        preview_panel.set_job_summaries([summary])

        assert "Learning metadata" in preview_panel.learning_metadata_label.cget("text")
