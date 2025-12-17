from __future__ import annotations

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.stage_models import StageType
from src.queue.job_model import Job
from src.utils.snapshot_builder_v2 import build_job_snapshot, normalized_job_from_snapshot


def test_build_job_snapshot_includes_expected_fields():
    record = NormalizedJobRecord(
        job_id="snapshot-job",
        config={"model": "test", "prompt": "sunset", "negative_prompt": "blur"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=123.0,
        randomizer_summary={"enabled": False},
    )
    job = Job(
        job_id="snapshot-job",
        config_snapshot=record.to_queue_snapshot(),
        run_mode="queue",
        source="gui",
        prompt_source="manual",
    )
    snapshot = build_job_snapshot(job, record, run_config={"run_mode": "queue"})
    assert snapshot["schema_version"] == "1.0"
    assert snapshot["job_id"] == job.job_id
    assert snapshot["run_config"]["run_mode"] == "queue"
    assert "normalized_job" in snapshot
    assert snapshot["effective_prompts"]["positive"] == "sunset"
    assert snapshot["stage_metadata"]["stages"] == []
    assert "seed_info" in snapshot
    assert "model_selection" in snapshot
    reconstructed = normalized_job_from_snapshot(snapshot)
    assert reconstructed is not None
    assert reconstructed.job_id == record.job_id
    assert reconstructed.seed == record.seed


def test_build_job_snapshot_repairs_pack_metadata():
    stage = StageConfig(
        stage_type=StageType.TXT2IMG,
        enabled=True,
        steps=20,
        cfg_scale=7.5,
        sampler_name="Euler a",
    )
    record = NormalizedJobRecord(
        job_id="pack-job",
        config={"prompt": "cosmic art"},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        stage_chain=[stage],
    )
    record.prompt_source = "pack"
    record.prompt_pack_id = ""
    record.prompt_pack_name = ""
    job = Job(
        job_id="pack-job",
        priority=1,
        prompt_source="pack",
        prompt_pack_id="pack-123",
        config_snapshot={},
        run_mode="queue",
        source="gui",
    )
    job.prompt_pack_name = "Pack 123"
    snapshot = build_job_snapshot(job, record, run_config={"prompt_source": "pack"})
    reconstructed = normalized_job_from_snapshot(snapshot)
    assert reconstructed is not None
    assert reconstructed.prompt_pack_id == "pack-123"
    assert reconstructed.prompt_pack_name == "Pack 123"
