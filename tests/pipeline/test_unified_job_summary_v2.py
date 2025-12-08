from datetime import datetime

from src.pipeline.job_models_v2 import (
    PackUsageInfo,
    StagePromptInfo,
    NormalizedJobRecord,
    UnifiedJobSummary,
    JobStatusV2,
)
from src.queue.job_model import Job, JobStatus


def _make_stage_info() -> StagePromptInfo:
    return StagePromptInfo(
        original_prompt="orig",
        final_prompt="final",
        original_negative_prompt="orig-neg",
        final_negative_prompt="final-neg",
        global_negative_applied=True,
        global_negative_terms="gneg",
    )


def test_normalized_job_record_generates_summary() -> None:
    record = NormalizedJobRecord(
        job_id="job-123",
        config={
            "prompt": "manual prompt",
            "model": "juggernaut",
            "stages": ["txt2img", "upscale"],
        },
        path_output_dir="out",
        filename_template="{seed}",
        created_ts=1700000000.0,
        txt2img_prompt_info=_make_stage_info(),
        pack_usage=[
            PackUsageInfo(pack_name="pack-a"),
            PackUsageInfo(pack_name="pack-b"),
        ],
    )

    summary = record.to_unified_summary(JobStatusV2.QUEUED)

    assert summary.job_id == "job-123"
    assert summary.model_name == "juggernaut"
    assert summary.positive_preview == "final"
    assert summary.negative_preview == "final-neg"
    assert summary.stages == "txt2img + upscale"
    assert summary.num_parts == 2
    assert summary.num_expected_images == 1
    assert summary.status == JobStatusV2.QUEUED
    assert isinstance(summary.created_at, datetime)


def test_unified_summary_can_build_from_job() -> None:
    job = Job(job_id="job-999", pipeline_config=None)
    job.config_snapshot = {"prompt": "fallback", "model": "default-model"}

    summary = UnifiedJobSummary.from_job(job, JobStatusV2.RUNNING)

    assert summary.status == JobStatusV2.RUNNING
    assert summary.positive_preview == "fallback"
    assert summary.model_name == "default-model"
