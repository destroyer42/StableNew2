"""Tests for PreviewPanelV2 job-centric summary rendering (PR-GUI-G)."""

from __future__ import annotations

import tkinter as tk
from datetime import datetime

import pytest

from src.gui.app_state_v2 import PackJobEntry
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
    label: str = "sd_xl_base_1.0 | seed=12345",
    positive_preview: str = "test prompt",
    negative_preview: str | None = None,
    stages_display: str = "txt2img",
    estimated_images: int = 1,
    created_at: datetime | None = None,
) -> JobUiSummary:
    """Build a minimal JobUiSummary for testing."""
    return JobUiSummary(
        job_id=job_id,
        label=label,
        positive_preview=positive_preview,
        negative_preview=negative_preview,
        stages_display=stages_display,
        estimated_images=estimated_images,
        created_at=created_at,
    )


class TestPreviewPanelSummary:
    """JobUiSummary rendering for PreviewPanelV2."""

    def test_renders_job_count(self, preview_panel):
        summaries = [make_ui_summary(job_id=f"job-{i}") for i in range(3)]
        preview_panel.set_job_summaries(summaries)

        assert "Jobs: 3" in preview_panel.job_count_label.cget("text")

    def test_renders_prompt(self, preview_panel):
        summary = make_ui_summary(positive_preview="A beautiful sunset")
        preview_panel.set_job_summaries([summary])

        text = preview_panel.prompt_text.get("1.0", "end").strip()
        assert "beautiful sunset" in text

    def test_renders_negative_prompt(self, preview_panel):
        summary = make_ui_summary(negative_preview="bad quality, blurry")
        preview_panel.set_job_summaries([summary])

        text = preview_panel.negative_prompt_text.get("1.0", "end").strip()
        assert "bad quality" in text

    def test_renders_label(self, preview_panel):
        summary = make_ui_summary(label="realisticVision_v51 | seed=99999")
        preview_panel.set_job_summaries([summary])

        assert "realisticVision_v51" in preview_panel.model_label.cget("text")
        assert "99999" in preview_panel.model_label.cget("text")

    def test_renders_stages(self, preview_panel):
        summary = make_ui_summary(stages_display="txt2img → upscale")
        preview_panel.set_job_summaries([summary])

        assert "txt2img" in preview_panel.stage_summary_label.cget("text")

    def test_clears_when_no_summaries(self, preview_panel):
        preview_panel.set_job_summaries([make_ui_summary()])
        preview_panel.set_job_summaries([])

        assert preview_panel.job_count_label.cget("text") == "No job selected"
        assert preview_panel.prompt_text.get("1.0", "end").strip() == ""

    def test_stage_flags_display(self, preview_panel):
        summary = make_ui_summary()
        preview_panel.set_job_summaries([summary])

        flags = preview_panel.stage_flags_label.cget("text")
        assert "Refiner: OFF" in flags  # Default is False

    def test_learning_metadata_placeholder(self, preview_panel):
        summary = make_ui_summary()
        preview_panel.set_job_summaries([summary])

        assert "Learning metadata" in preview_panel.learning_metadata_label.cget("text")

    def test_update_from_job_draft_builds_summary(self, preview_panel):
        entry = PackJobEntry(
            pack_id="pack-1",
            pack_name="Pack one",
            config_snapshot={
                "model": "pack-model",
                "sampler": "Euler a",
                "steps": 25,
                "cfg_scale": 7.5,
                "seed": 12345,
                "output_dir": "output",
            },
            prompt_text="Testing prompt",
            negative_prompt_text="bad stuff",
            stage_flags={
                "txt2img": True,
                "adetailer": True,
                "upscale": False,
                "refiner": False,
                "hires": False,
            },
            randomizer_metadata={"enabled": False, "max_variants": 1},
        )
        job_draft = type("JD", (), {"packs": [entry]})()
        preview_panel.update_from_job_draft(job_draft)

        assert "Job: 1" in preview_panel.job_count_label.cget("text")
        assert "Testing prompt" in preview_panel.prompt_text.get("1.0", "end")
        assert preview_panel.add_to_queue_button.instate(["!disabled"])
