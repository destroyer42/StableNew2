"""Tests for the JobUiSummary helpers in NormalizedJobRecord."""

from __future__ import annotations

from src.pipeline.job_models_v2 import NormalizedJobRecord


def make_job_record(**kwargs):
    base_config = {
        "model": "base-model",
        "prompt": "A prompt",
        "negative_prompt": "bad, buggy, blurry",
        "stages": ["txt2img", "upscale"],
        "refiner_enabled": True,
        "hires_enabled": True,
        "upscale_enabled": True,
    }
    base_config.update(kwargs.get("config", {}))
    return NormalizedJobRecord(
        job_id=kwargs.get("job_id", "job-001"),
        config=base_config,
        path_output_dir=kwargs.get("path_output_dir", "output"),
        filename_template=kwargs.get("filename_template", "{seed}"),
        seed=kwargs.get("seed", 123),
        variant_index=kwargs.get("variant_index", 0),
        variant_total=kwargs.get("variant_total", 2),
        batch_index=kwargs.get("batch_index", 0),
        batch_total=kwargs.get("batch_total", 1),
        randomizer_summary=kwargs.get("randomizer_summary"),
    )


def test_to_ui_summary_includes_negative_prompt_and_flags():
    job = make_job_record()
    summary = job.to_ui_summary()

    assert summary.negative_preview.startswith("bad")
    assert summary.stages_display == "txt2img → upscale"
    assert summary.estimated_images == 2  # variant_total


def test_to_ui_summary_formats_label():
    job = make_job_record(seed=999)
    summary = job.to_ui_summary()

    assert "base-model" in summary.label
    assert "seed=999" in summary.label


def test_to_ui_summary_upscale_detected_from_stages():
    job = make_job_record(config={"stages": ["txt2img", "upscale", "adetailer"]})
    summary = job.to_ui_summary()

    assert "upscale" in summary.stages_display.lower()
