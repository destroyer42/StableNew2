from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from src.controller.svd_controller import SVDController
from src.state.output_routing import OUTPUT_ROUTE_TESTING
from src.video.svd_config import SVDConfig
from src.video.svd_models import get_default_svd_cache_dir


def test_submit_svd_job_enqueues_svd_native_njr(tmp_path, monkeypatch) -> None:
    captured = {}
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")

    def _submit_njrs(njrs, policy):
        captured["njrs"] = njrs
        captured["policy"] = policy
        return ["job-svd-001"]

    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(submit_njrs=_submit_njrs),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda _config, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )

    job_id = controller.submit_svd_job(
        source_image_path=source_path,
        config=SVDConfig(),
        output_route=OUTPUT_ROUTE_TESTING,
    )

    assert job_id == "job-svd-001"
    njr = captured["njrs"][0]
    assert njr.start_stage == "svd_native"
    assert njr.input_image_paths == (str(source_path),)
    assert "SVD animation source" in njr.positive_prompt
    assert [stage.stage_type for stage in njr.stage_chain] == ["svd_native"]
    assert njr.config["pipeline"]["output_route"] == OUTPUT_ROUTE_TESTING
    assert captured["policy"].start_when_idle is False


def test_get_postprocess_capabilities_exposes_runtime_status() -> None:
    app_controller = SimpleNamespace(output_dir="output", job_service=Mock())
    controller = SVDController(app_controller=app_controller, svd_service=Mock())

    result = controller.get_postprocess_capabilities()

    assert "codeformer" in result
    assert "realesrgan" in result
    assert "rife" in result
    assert "gfpgan" in result


def test_build_default_config_is_conservative_xt_core_baseline() -> None:
    app_controller = SimpleNamespace(output_dir="output", job_service=Mock())
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    result = controller.build_default_config()

    assert result.preprocess.resize_mode == "center_crop"
    assert result.inference.model_id == "stabilityai/stable-video-diffusion-img2vid-xt"
    assert result.inference.motion_bucket_id == 48
    assert result.inference.noise_aug_strength == 0.01
    assert result.inference.decode_chunk_size == 2
    assert result.inference.num_inference_steps == 25
    assert result.inference.local_files_only is True
    assert result.inference.cache_dir == str(get_default_svd_cache_dir())
    assert result.postprocess.face_restore.enabled is False
    assert result.postprocess.interpolation.enabled is False
    assert result.postprocess.upscale.enabled is False


def test_submit_svd_job_rejects_missing_rife_runtime(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("STABLENEW_RIFE_EXE", raising=False)
    monkeypatch.setenv("PATH", "")
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(submit_njrs=lambda *_args, **_kwargs: ["job-svd-001"]),
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
