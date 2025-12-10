from datetime import datetime

from src.pipeline.job_models_v2 import (
    LoRATag,
    PackUsageInfo,
    StageConfig,
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
        prompt_pack_id="pack-angelic",
        prompt_pack_name="Angelic Warriors",
        positive_prompt="masterpiece prompt",
        negative_prompt="neg block",
        positive_embeddings=["stable_yogis", "realism"],
        lora_tags=[LoRATag(name="add-detail-xl", weight=0.65)],
        matrix_slot_values={
            "environment": "volcanic lair",
            "lighting": "hellish backlight",
        },
        base_model="juggernautXL_ragnarokBy",
        sampler_name="Euler a",
        cfg_scale=6.1,
        steps=34,
        width=1216,
        height=832,
        stage_chain=[
            StageConfig(stage_type="txt2img", enabled=True, steps=34, cfg_scale=6.1),
            StageConfig(stage_type="upscale", enabled=True),
        ],
        randomization_enabled=True,
        matrix_mode="rotate",
        variant_index=2,
        batch_index=1,
        images_per_prompt=2,
        loop_count=1,
    )

    summary = record.to_unified_summary()

    assert summary.job_id == "job-123"
    assert summary.prompt_pack_id == "pack-angelic"
    assert summary.prompt_pack_name == "Angelic Warriors"
    assert summary.positive_prompt_preview == "masterpiece prompt"
    assert summary.negative_prompt_preview == "neg block"
    assert summary.lora_preview == "add-detail-xl(0.65)"
    assert summary.embedding_preview == "stable_yogis + realism"
    assert summary.base_model == "juggernautXL_ragnarokBy"
    assert summary.stage_chain_labels == ["txt2img", "upscale"]
    assert summary.matrix_mode == "rotate"
    assert "environment=volcanic lair" in summary.matrix_slot_values_preview
    assert summary.variant_index == 2
    assert summary.batch_index == 1
    assert summary.estimated_image_count == 2
    assert summary.status == "QUEUED"
    assert isinstance(summary.created_at, datetime)


def test_unified_summary_can_build_from_job() -> None:
    job = Job(job_id="job-999")
    job.config_snapshot = {"prompt": "fallback", "model": "default-model"}

    summary = UnifiedJobSummary.from_job(job, JobStatusV2.RUNNING)

    assert summary.status == "RUNNING"
    assert summary.positive_prompt_preview == ""
    assert summary.base_model == "unknown"
