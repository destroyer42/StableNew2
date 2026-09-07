from __future__ import annotations

import pytest

from src.pipeline.job_models_v2 import SourceDescriptor, SourceKind
from src.queue.job_model import Job
from src.utils.snapshot_builder_v2 import build_job_snapshot, normalized_job_from_snapshot
from tests.helpers.njr_factory import make_pipeline_njr


def test_build_job_snapshot_includes_expected_fields():
    record = make_pipeline_njr(
        job_id="snapshot-job",
        config={"model": "test", "prompt": "sunset", "negative_prompt": "blur"},
        seed=42,
        positive_prompt="sunset",
        negative_prompt="blur",
        randomizer_summary={"enabled": False},
        intent_config={"run_mode": "queue", "source": "run"},
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
    assert snapshot["config_layers"]["intent_config"]["source"] == "run"
    assert snapshot["normalized_job"]["workload"]["intent_config"]["source"] == "run"
    assert "normalized_job" in snapshot
    assert snapshot["effective_prompts"]["positive"] == "sunset"
    assert snapshot["stage_metadata"]["stages"] == []
    assert "seed_info" in snapshot
    assert "model_selection" in snapshot
    reconstructed = normalized_job_from_snapshot(snapshot)
    assert reconstructed is not None
    assert reconstructed.job_id == record.job_id
    assert reconstructed.seed == record.seed
    assert reconstructed.intent_config["source"] == "run"


def test_prompt_pack_identity_cannot_be_repaired_at_snapshot_time():
    with pytest.raises(ValueError, match="requires source.id"):
        SourceDescriptor(kind=SourceKind.PROMPT_PACK)
