"""
Test that build_run_plan_from_njr creates jobs for enabled stages in stage_chain.
"""
from src.pipeline.run_plan import build_run_plan_from_njr
from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig


def _make_njr(stage_chain: list[StageConfig]) -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="test-001",
        config={},
        path_output_dir="./test_output",
        filename_template="test_{index}",
        positive_prompt="beautiful woman portrait",
        stage_chain=stage_chain,
    )


def test_build_run_plan_respects_enabled_stages() -> None:
    njr = _make_njr(
        [
            StageConfig(stage_type="txt2img", enabled=True),
            StageConfig(stage_type="adetailer", enabled=True),
            StageConfig(stage_type="upscale", enabled=True),
        ]
    )

    plan = build_run_plan_from_njr(njr)

    assert len(plan.jobs) == 3, f"Expected 3 jobs, got {len(plan.jobs)}"
    assert [job.stage_name for job in plan.jobs] == ["txt2img", "adetailer", "upscale"]
    assert plan.enabled_stages == ["txt2img", "adetailer", "upscale"]
    assert plan.total_jobs == 3


def test_build_run_plan_falls_back_when_all_disabled() -> None:
    njr = _make_njr(
        [
            StageConfig(stage_type="txt2img", enabled=False),
            StageConfig(stage_type="adetailer", enabled=False),
        ]
    )

    plan = build_run_plan_from_njr(njr)

    assert len(plan.jobs) == 1
    assert plan.jobs[0].stage_name == "txt2img"
    assert plan.enabled_stages == ["txt2img"]
