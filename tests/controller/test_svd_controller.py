from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from PIL import Image

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
        config=SVDConfig.from_dict({"inference": {"num_frames": 25}}),
        output_route=OUTPUT_ROUTE_TESTING,
    )

    assert job_id == "job-svd-001"
    njr = captured["njrs"][0]
    assert njr.start_stage == "svd_native"
    assert njr.input_image_paths == (str(source_path),)
    assert "SVD animation source" in njr.positive_prompt
    assert [stage.stage_type for stage in njr.stage_chain] == ["svd_native"]
    assert njr.config["svd_native"]["inference"]["num_frames"] == 25
    assert njr.config["pipeline"]["output_route"] == OUTPUT_ROUTE_TESTING
    assert captured["policy"].start_when_idle is False


def test_submit_svd_job_persists_resolved_target_dimensions(tmp_path, monkeypatch) -> None:
    captured = {}
    source_path = tmp_path / "portrait.png"
    source_path.write_bytes(b"png")

    def _submit_njrs(njrs, _policy):
        captured["njr"] = njrs[0]
        return ["job-svd-portrait"]

    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(submit_njrs=_submit_njrs),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda _config, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )
    config = SVDConfig.from_dict(
        {
            "preprocess": {
                "target_width": 640,
                "target_height": 960,
                "resize_mode": "center_crop",
            }
        }
    )

    assert (
        controller.submit_svd_job(source_image_path=source_path, config=config)
        == "job-svd-portrait"
    )

    preprocess = captured["njr"].config["svd_native"]["preprocess"]
    assert preprocess["target_width"] == 640
    assert preprocess["target_height"] == 960
    assert preprocess["resize_mode"] == "center_crop"


def _write_image(path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, color=(32, 64, 96)).save(path)


def test_submit_svd_folder_batch_submits_once_in_discovery_order_and_resolves_geometry(
    tmp_path, monkeypatch
) -> None:
    _write_image(tmp_path / "z_landscape.png", (1600, 800))
    _write_image(tmp_path / "a_portrait.jpg", (800, 1600))
    (tmp_path / "notes.txt").write_text("ignored")
    captured = {}

    def _submit_njrs(njrs, policy):
        captured["njrs"] = list(njrs)
        captured["policy"] = policy
        return [f"job-{index}" for index, _ in enumerate(njrs)]

    app_controller = SimpleNamespace(
        output_dir=str(tmp_path), job_service=SimpleNamespace(submit_njrs=_submit_njrs)
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    preflight = Mock(return_value=SimpleNamespace(available=True, blocking_reasons=()))
    monkeypatch.setattr("src.controller.svd_controller.get_svd_preflight", preflight)

    job_ids = controller.submit_svd_folder_batch(
        folder=tmp_path,
        config=SVDConfig.from_dict({"inference": {"seed": 42}}),
        match_source_aspect=True,
        output_route=OUTPUT_ROUTE_TESTING,
    )

    assert job_ids == ["job-0", "job-1"]
    assert preflight.call_count == 1
    assert captured["policy"].start_when_idle is False
    assert [Path(njr.input_image_paths[0]).name for njr in captured["njrs"]] == [
        "a_portrait.jpg",
        "z_landscape.png",
    ]
    assert all(len(njr.input_image_paths) == 1 for njr in captured["njrs"])
    assert all([stage.stage_type for stage in njr.stage_chain] == ["svd_native"] for njr in captured["njrs"])
    preprocesses = [njr.config["svd_native"]["preprocess"] for njr in captured["njrs"]]
    assert [(item["target_width"], item["target_height"]) for item in preprocesses] == [
        (576, 1024),
        (1024, 576),
    ]
    assert [njr.config["svd_native"]["inference"]["seed"] for njr in captured["njrs"]] == [42, 42]


def test_submit_svd_folder_batch_rejects_invalid_candidate_without_submission(tmp_path, monkeypatch) -> None:
    _write_image(tmp_path / "valid.png", (768, 768))
    (tmp_path / "broken.webp").write_bytes(b"not a webp")
    submit = Mock()
    app_controller = SimpleNamespace(output_dir=str(tmp_path), job_service=SimpleNamespace(submit_njrs=submit))
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )

    try:
        controller.submit_svd_folder_batch(
            folder=tmp_path,
            config=SVDConfig(),
            match_source_aspect=False,
        )
        assert False, "expected invalid candidate to block the full batch"
    except RuntimeError as exc:
        assert "invalid image candidates" in str(exc)
    submit.assert_not_called()


def test_submit_svd_folder_batch_rejects_zero_compatible_sources_without_submission(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "notes.txt").write_text("ignored")
    submit = Mock()
    controller = SVDController(
        app_controller=SimpleNamespace(output_dir=str(tmp_path), job_service=SimpleNamespace(submit_njrs=submit)),
        svd_service=Mock(),
    )
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preflight must not run")),
    )

    try:
        controller.submit_svd_folder_batch(folder=tmp_path, config=SVDConfig(), match_source_aspect=False)
        assert False, "expected zero compatible sources to block submission"
    except RuntimeError as exc:
        assert "no compatible image files" in str(exc)
    submit.assert_not_called()


def test_submit_svd_folder_batch_fixed_target_and_blank_seed_are_preserved(tmp_path, monkeypatch) -> None:
    _write_image(tmp_path / "a.png", (768, 768))
    _write_image(tmp_path / "b.tiff", (900, 600))
    captured = {}
    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(
            submit_njrs=lambda njrs, _policy: captured.setdefault("njrs", list(njrs)) and ["a", "b"]
        ),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: SimpleNamespace(available=True, blocking_reasons=()),
    )
    controller.submit_svd_folder_batch(
        folder=tmp_path,
        config=SVDConfig.from_dict({"preprocess": {"target_width": 768, "target_height": 768}}),
        match_source_aspect=False,
    )
    for njr in captured["njrs"]:
        preprocess = njr.config["svd_native"]["preprocess"]
        assert (preprocess["target_width"], preprocess["target_height"]) == (768, 768)
        assert njr.config["svd_native"]["inference"]["seed"] is None


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
    assert result.inference.num_frames == 14
    assert result.inference.motion_bucket_id == 48
    assert result.inference.noise_aug_strength == 0.01
    assert result.inference.decode_chunk_size == 2
    assert result.inference.num_inference_steps == 25
    assert result.inference.local_files_only is True
    assert result.inference.cpu_offload is True
    assert result.inference.forward_chunking is True
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


def test_submit_svd_job_rejects_unsupported_rife_multiplier_before_preflight(
    tmp_path, monkeypatch
) -> None:
    source_path = tmp_path / "source.png"
    source_path.write_bytes(b"png")
    app_controller = SimpleNamespace(
        output_dir=str(tmp_path),
        job_service=SimpleNamespace(submit_njrs=Mock()),
    )
    controller = SVDController(app_controller=app_controller, svd_service=Mock())
    monkeypatch.setattr(
        "src.controller.svd_controller.get_svd_preflight",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("preflight must not run")),
    )

    config = SVDConfig.from_dict(
        {"postprocess": {"interpolation": {"enabled": True, "multiplier": 3}}}
    )

    try:
        controller.submit_svd_job(source_image_path=source_path, config=config)
        assert False, "expected unsupported multiplier admission failure"
    except RuntimeError as exc:
        assert "only 2x or 4x" in str(exc)
