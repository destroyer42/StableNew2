"""Tests for the JobUiSummary helpers in NormalizedJobRecord."""

from __future__ import annotations

from src.pipeline.job_models_v2 import NormalizedJobRecord
from tests.helpers.njr_factory import make_pipeline_njr, make_stage_config


def make_job_record(
    *,
    stages: tuple[str, ...] = ("txt2img", "upscale"),
    seed: int = 123,
    **overrides,
) -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id=overrides.pop("job_id", "job-001"),
        positive_prompt="A prompt",
        negative_prompt="bad, buggy, blurry",
        base_model="base-model",
        seed=seed,
        variant_total=2,
        stage_chain=[make_stage_config(stage, model="base-model") for stage in stages],
        **overrides,
    )


def test_to_ui_summary_includes_negative_prompt_and_stages():
    job = make_job_record()
    summary = job.to_ui_summary()

    assert summary.negative_preview.startswith("bad")
    assert summary.stages_display == "txt2img + upscale"
    assert summary.estimated_images == 1  # images_per_prompt * loop_count


def test_to_ui_summary_formats_label():
    job = make_job_record(seed=999)
    summary = job.to_ui_summary()

    assert "base-model" in summary.label
    assert "seed=999" in summary.label


def test_to_ui_summary_upscale_detected_from_stages():
    job = make_job_record(stages=("txt2img", "upscale", "adetailer"))
    summary = job.to_ui_summary()

    assert "upscale" in summary.stages_display.lower()
