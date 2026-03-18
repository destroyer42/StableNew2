from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.svd_controller import SVDController
from src.pipeline.job_requests_v2 import PipelineRunRequest
from src.state.output_routing import OUTPUT_ROUTE_TESTING
from src.video.svd_config import SVDConfig


def test_submit_svd_job_enqueues_svd_native_njr(tmp_path) -> None:
    captured = {}
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")

    def _enqueue_njrs(njrs, request: PipelineRunRequest):
        captured["njrs"] = njrs
        captured["request"] = request
        return ["job-svd-001"]

    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(enqueue_njrs=_enqueue_njrs),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())

    job_id = controller.submit_svd_job(
        source_image_path=source_path,
        config=SVDConfig(),
        output_route=OUTPUT_ROUTE_TESTING,
    )

    assert job_id == "job-svd-001"
    njr = captured["njrs"][0]
    assert njr.start_stage == "svd_native"
    assert njr.input_image_paths == [str(source_path)]
    assert "SVD animation source" in njr.positive_prompt
    assert [stage.stage_type for stage in njr.stage_chain] == ["svd_native"]
    assert njr.config["pipeline"]["output_route"] == OUTPUT_ROUTE_TESTING
    request = captured["request"]
    assert request.prompt_pack_id == "svd_native"
    assert request.requested_job_label == "SVD Img2Vid"


def test_get_postprocess_capabilities_exposes_runtime_status() -> None:
    app_controller = SimpleNamespace(output_dir="output", job_service=Mock())
    controller = SVDController(app_controller=app_controller, svd_service=Mock())

    result = controller.get_postprocess_capabilities()

    assert "codeformer" in result
    assert "realesrgan" in result
    assert "rife" in result
    assert "gfpgan" in result


def test_build_default_config_enables_available_postprocess(monkeypatch) -> None:
    app_controller = SimpleNamespace(output_dir="output", job_service=Mock())
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    captured = {}
    default_config = SVDConfig.from_dict(
        {
            "postprocess": {
                "face_restore": {"enabled": True},
                "interpolation": {"enabled": True, "executable_path": "C:/tools/rife.exe"},
                "upscale": {"enabled": True},
            }
        }
    )
    def _fake_apply(config: SVDConfig) -> SVDConfig:
        captured["config"] = config
        return default_config

    monkeypatch.setattr("src.controller.svd_controller.apply_recommended_svd_defaults", _fake_apply)

    result = controller.build_default_config()

    base_config = captured["config"]
    assert base_config.preprocess.resize_mode == "center_crop"
    assert base_config.inference.motion_bucket_id == 48
    assert base_config.inference.noise_aug_strength == 0.01
    assert base_config.inference.num_inference_steps == 36
    assert result.postprocess.face_restore.enabled is True
    assert result.postprocess.interpolation.enabled is True
    assert result.postprocess.upscale.enabled is True


def test_submit_svd_job_rejects_missing_rife_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(enqueue_njrs=lambda *_args, **_kwargs: ["job-svd-001"]),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    config = SVDConfig.from_dict(
        {
            "postprocess": {
                "interpolation": {
                    "enabled": True,
                    "multiplier": 2,
                }
            }
        }
    )

    try:
        controller.submit_svd_job(source_image_path=source_path, config=config)
        assert False, "expected submit_svd_job to reject missing RIFE runtime"
    except RuntimeError as exc:
        assert "RIFE" in str(exc)
