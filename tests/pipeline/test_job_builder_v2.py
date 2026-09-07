from __future__ import annotations

from src.pipeline.job_builder_v2 import JobBuilderV2
from src.pipeline.job_models_v2 import BatchSettings


def test_job_builder_v2_has_no_pack_shaped_submission_api() -> None:
    assert not hasattr(JobBuilderV2, "build_from_run_request")


def test_job_builder_v2_builds_image_njrs_from_typed_builder_inputs() -> None:
    builder = JobBuilderV2(id_fn=lambda: "job-abc")
    records = builder.build_jobs(
        base_config={
            "model": "sdxl",
            "prompt": "a prompt",
            "negative_prompt": "bad",
            "steps": 20,
            "cfg_scale": 7.0,
        },
        batch_settings=BatchSettings(batch_runs=1),
    )

    assert len(records) == 1
    assert records[0].job_id == "job-abc"
    assert records[0].workload_kind.value == "image"
