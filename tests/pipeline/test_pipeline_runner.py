from unittest.mock import Mock

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunResult, PipelineRunner


def _minimal_normalized_record() -> NormalizedJobRecord:
    return NormalizedJobRecord(
        job_id="runner-test",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        randomizer_summary=None,
        stage_chain=[
            StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a")
        ],
    )


def test_run_njr_is_only_public_entrypoint() -> None:
    runner = PipelineRunner(Mock(), Mock())
    assert hasattr(runner, "run_njr")
    assert not hasattr(runner, "run")


def test_run_njr_delegates_to_executor() -> None:
    runner = PipelineRunner(Mock(), Mock())
    record = _minimal_normalized_record()
    expected = PipelineRunResult(
        run_id="test-run",
        success=True,
        error=None,
        variants=[],
        learning_records=[],
        metadata={},
        stage_plan=None,
        stage_events=[],
    )
    runner._execute_with_config = Mock(return_value=expected)
    result = runner.run_njr(record, cancel_token=None)
    assert result is expected
    runner._execute_with_config.assert_called_once()
