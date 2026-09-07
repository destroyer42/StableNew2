"""Tests ensuring NormalizedJobRecord → JobView unification."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from tests.helpers.njr_factory import make_pipeline_njr


def _sample_record() -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id="unify-001",
        config={"prompt": "aurora", "model": "sdxl"},
        seed=42,
        base_model="sdxl-model",
        positive_prompt="aurora over the mountains",
        negative_prompt="bad anatomy",
        stage_chain=[
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"
            )
        ],
    )


def test_job_view_from_normalized_record() -> None:
    record = _sample_record()
    view = record.to_job_view(status="queued", created_at="2025-01-01T00:00:00Z")

    assert view.job_id == record.job_id
    assert view.model == record.base_model
    assert view.prompt == record.positive_prompt
    assert view.negative_prompt == record.negative_prompt
    assert view.status == "queued"
    assert "seed=42" in view.label
    assert view.estimated_images == 1
    assert view.stages_display == "txt2img"


def test_job_view_includes_variant_and_batch_labels() -> None:
    record = _sample_record()
    record = replace(
        record,
        provenance=replace(
            record.provenance,
            variant_total=3,
            variant_index=1,
            batch_total=2,
            batch_index=0,
        ),
    )

    view = record.to_job_view(status="queued", created_at="2025-01-01T00:00:00Z")
    assert "[v2/3]" in view.label
    assert "[b1/2]" in view.label


def test_legacy_dto_names_not_in_controller_sources() -> None:
    legacy_names = {"JobHistoryItemDTO", "JobQueueItemDTO", "JobUiSummary"}
    paths = [
        Path("src/controller/job_service.py"),
        Path("src/controller/job_history_service.py"),
        Path("src/history/history_record.py"),
        Path("src/history/job_history_store.py"),
        Path("src/pipeline/replay_engine.py"),
        Path("src/pipeline/run_plan.py"),
        Path("tests/controller/test_job_history_service.py"),
        Path("tests/history/test_history_replay_integration.py"),
        Path("tests/history/test_history_store_recording_v2.py"),
    ]
    for path in paths:
        text = path.read_text()
        for name in legacy_names:
            assert name not in text, f"{name} still present in {path}"
