from __future__ import annotations

from src.controller.pipeline_controller import PipelineController
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.stage_models import StageType


def _make_stage() -> StageConfig:
    return StageConfig(
        stage_type=StageType.TXT2IMG,
        enabled=True,
        steps=12,
        cfg_scale=7.5,
        sampler_name="Euler a",
    )


def _make_record(prompt_source: str, prompt_pack_id: str | None) -> NormalizedJobRecord:
    record = NormalizedJobRecord(
        job_id="test-njr",
        config={"prompt": "test prompt"},
        path_output_dir="output",
        filename_template="{seed}",
        stage_chain=[_make_stage()],
    )
    record.prompt_source = prompt_source
    record.prompt_pack_id = prompt_pack_id or ""
    return record


def test_is_pack_job_property_true_for_pack() -> None:
    record = _make_record(prompt_source="pack", prompt_pack_id="pack-id")
    assert record.is_pack_job


def test_split_queueable_records_filters_packless() -> None:
    controller = PipelineController.__new__(PipelineController)
    pack_record = _make_record(prompt_source="pack", prompt_pack_id="pack-id")
    manual_record = _make_record(prompt_source="manual", prompt_pack_id=None)
    queueable, non_queueable = controller._split_queueable_records(
        [pack_record, manual_record]
    )
    assert pack_record in queueable
    assert manual_record in non_queueable
