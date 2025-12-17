from unittest.mock import Mock

from src.pipeline.job_models_v2 import NormalizedJobRecord, StageConfig
from src.pipeline.pipeline_runner import PipelineRunner, PipelineRunResult, normalize_run_result


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
            StageConfig(
                stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"
            )
        ],
    )


def test_run_njr_is_only_public_entrypoint() -> None:
    runner = PipelineRunner(Mock(), Mock())
    assert hasattr(runner, "run_njr")
    assert not hasattr(runner, "run")


def test_run_njr_delegates_to_executor() -> None:
    runner = PipelineRunner(Mock(), Mock())
    record = _minimal_normalized_record()
    pipeline = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline
    result = runner.run_njr(record, cancel_token=None)
    pipeline.run_txt2img_stage.assert_called_once()
    assert result.success is True
    assert result.variants == [{"path": "output.png"}]


def test_pipeline_run_result_to_dict_and_back() -> None:
    result = PipelineRunResult(
        run_id="roundtrip-001",
        success=True,
        error=None,
        variants=[{"variant": "a"}],
        learning_records=[],
        metadata={"note": "test"},
        stage_plan=None,
        stage_events=[{"stage": "txt2img"}],
    )
    data = result.to_dict()
    assert data["run_id"] == "roundtrip-001"
    assert data["metadata"]["note"] == "test"
    restored = PipelineRunResult.from_dict(data)
    assert restored.run_id == result.run_id
    assert restored.success == result.success
    assert restored.metadata == result.metadata


def test_normalize_run_result_accepts_dicts_and_defaults() -> None:
    canonical = normalize_run_result(
        {"run_id": "from-dict", "success": True}, default_run_id="fallback"
    )
    assert canonical["run_id"] == "from-dict"
    assert canonical["success"] is True
    fallback = normalize_run_result("unexpected", default_run_id="fallback")
    assert fallback["run_id"] == "fallback"
    assert fallback["success"] is False
    assert fallback["error"] == "unexpected"
