"""
Test that build_run_plan_from_njr creates jobs for enabled stages in stage_chain.
"""

import pytest

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.run_plan import build_run_plan_from_njr
from tests.helpers.njr_factory import make_pipeline_njr


def _make_njr(stage_chain: list[StageConfig]) -> NormalizedJobRecord:
    return make_pipeline_njr(
        job_id="test-001",
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


def test_build_run_plan_skips_disabled_stages() -> None:
    njr = _make_njr(
        [
            StageConfig(stage_type="txt2img", enabled=True),
            StageConfig(stage_type="adetailer", enabled=False),
        ]
    )

    plan = build_run_plan_from_njr(njr)

    assert [job.stage_name for job in plan.jobs] == ["txt2img"]
    assert plan.enabled_stages == ["txt2img"]


def test_njr_rejects_stage_chain_with_no_enabled_stage() -> None:
    # The NJR envelope guarantees at least one enabled stage, so a run plan never needs a
    # synthetic "all disabled -> txt2img" fallback.
    with pytest.raises(ValueError, match="at least one enabled stage"):
        _make_njr(
            [
                StageConfig(stage_type="txt2img", enabled=False),
                StageConfig(stage_type="adetailer", enabled=False),
            ]
        )


def test_build_run_plan_normalizes_legacy_upscale_before_adetailer() -> None:
    njr = _make_njr(
        [
            StageConfig(stage_type="txt2img", enabled=True),
            StageConfig(stage_type="upscale", enabled=True),
            StageConfig(stage_type="adetailer", enabled=True),
        ]
    )

    plan = build_run_plan_from_njr(njr)

    assert [job.stage_name for job in plan.jobs] == ["txt2img", "adetailer", "upscale"]
    assert plan.enabled_stages == ["txt2img", "adetailer", "upscale"]
