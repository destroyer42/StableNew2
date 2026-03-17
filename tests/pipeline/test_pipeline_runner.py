from pathlib import Path
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
    pipeline.client = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": "output.png"}
    runner._pipeline = pipeline
    result = runner.run_njr(record, cancel_token=None)
    pipeline.client.free_vram.assert_called_once_with(
        unload_model=False,
        refresh_checkpoints=False,
    )
    pipeline.run_txt2img_stage.assert_called_once()
    assert result.success is True
    assert result.variants[0]["path"] == "output.png"
    assert result.variants[0]["artifact"]["primary_path"] == "output.png"


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


def test_normalize_run_result_preserves_missing_success_as_unknown() -> None:
    canonical = normalize_run_result({"run_id": "legacy-dict"}, default_run_id="fallback")

    assert canonical["run_id"] == "legacy-dict"
    assert canonical["success"] is None
    assert canonical["error"] is None


def test_run_njr_dispatches_animatediff_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")
    record = NormalizedJobRecord(
        job_id="runner-animatediff",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="animatediff", enabled=True, extra={"enabled": True})],
        input_image_paths=[str(input_path)],
        start_stage="animatediff",
    )
    pipeline = Mock()
    pipeline.run_animatediff_stage.return_value = {
        "video_path": str(tmp_path / "clip.mp4"),
        "frame_paths": [str(tmp_path / "frame_000000.png")],
        "frame_count": 1,
    }
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    pipeline.run_animatediff_stage.assert_called_once()
    assert result.success is True
    assert result.metadata["animatediff_artifact"]["count"] == 1


def test_run_njr_dispatches_svd_native_stage(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    input_path = tmp_path / "seed.png"
    input_path.write_bytes(b"seed")
    output_video = tmp_path / "svd.mp4"
    manifest = tmp_path / "svd.json"
    preview = tmp_path / "preview.png"
    record = NormalizedJobRecord(
        job_id="runner-svd-native",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[StageConfig(stage_type="svd_native", enabled=True, extra={})],
        input_image_paths=[str(input_path)],
        start_stage="svd_native",
    )
    pipeline = Mock()
    pipeline.run_svd_native_stage.return_value = {
        "path": str(output_video),
        "video_path": str(output_video),
        "gif_path": None,
        "frame_paths": [],
        "manifest_path": str(manifest),
        "thumbnail_path": str(preview),
        "frame_count": 25,
    }
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    pipeline.run_svd_native_stage.assert_called_once()
    assert result.success is True
    assert result.metadata["svd_native_artifact"]["count"] == 1
    assert record.thumbnail_path == str(preview)
    assert record.output_paths == [str(output_video)]


def test_run_njr_fails_when_final_enabled_stage_produces_no_outputs(tmp_path: Path) -> None:
    runner = PipelineRunner(Mock(), Mock(), runs_base_dir=str(tmp_path / "runs"))
    record = NormalizedJobRecord(
        job_id="runner-final-stage-failure",
        config={},
        path_output_dir="output",
        filename_template="{seed}",
        seed=42,
        variant_index=0,
        variant_total=1,
        batch_index=0,
        batch_total=1,
        created_ts=0.0,
        stage_chain=[
            StageConfig(stage_type="txt2img", enabled=True, steps=20, cfg_scale=7.5, sampler_name="Euler a"),
            StageConfig(stage_type="animatediff", enabled=True, extra={"enabled": True}),
        ],
    )
    pipeline = Mock()
    pipeline.run_txt2img_stage.return_value = {"path": str(tmp_path / "image.png"), "all_paths": [str(tmp_path / "image.png")]}
    pipeline.run_animatediff_stage.return_value = None
    runner._pipeline = pipeline

    result = runner.run_njr(record, cancel_token=None)

    assert result.success is False
    assert result.error == "No images were generated successfully"
