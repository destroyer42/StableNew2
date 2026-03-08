from __future__ import annotations

from unittest.mock import Mock, patch

from src.controller.app_controller import AppController


def _build_controller() -> AppController:
    with patch("src.controller.app_controller.AppController.__init__", return_value=None):
        controller = AppController.__new__(AppController)
    controller.job_service = Mock()
    controller._append_log = Mock()
    controller._api_client = Mock()
    controller.cancel_token = None
    controller._build_reprocess_config = Mock(
        return_value={
            "steps": 20,
            "cfg_scale": 7.0,
            "img2img": {"denoising_strength": 0.2},
        }
    )
    return controller


def test_reprocess_with_prompt_delta_uses_metadata_baseline(tmp_path) -> None:
    controller = _build_controller()
    image = tmp_path / "img_a.png"
    image.write_bytes(b"")

    controller._extract_reprocess_baseline_from_image = Mock(
        return_value={
            "prompt": "portrait photo",
            "negative_prompt": "blurry",
            "model": "modelA.safetensors",
            "vae": "vaeA",
            "config": {
                "steps": 32,
                "img2img": {"denoising_strength": 0.42},
            },
        }
    )

    submitted = controller.on_reprocess_images_with_prompt_delta(
        image_paths=[str(image)],
        stages=["img2img", "adetailer"],
        prompt_delta="bending forward",
        negative_prompt_delta="extra hands",
        prompt_mode="append",
        negative_prompt_mode="append",
    )

    assert submitted == 1
    job = controller.job_service.submit_queued.call_args[0][0]
    njr = job._normalized_record
    assert njr.positive_prompt == "portrait photo, bending forward"
    assert njr.negative_prompt == "blurry, extra hands"
    assert njr.base_model == "modelA.safetensors"
    assert njr.config["steps"] == 32
    assert njr.config["img2img"]["denoising_strength"] == 0.42
    assert njr.config["vae"] == "vaeA"
    assert njr.config["txt2img"]["model"] == "modelA.safetensors"
    assert job.source == "review_tab"


def test_reprocess_with_prompt_replace_uses_fallback_without_metadata(tmp_path) -> None:
    controller = _build_controller()
    image = tmp_path / "img_b.png"
    image.write_bytes(b"")

    controller._extract_reprocess_baseline_from_image = Mock(return_value={})

    submitted = controller.on_reprocess_images_with_prompt_delta(
        image_paths=[str(image)],
        stages=["adetailer"],
        prompt_delta="new prompt",
        negative_prompt_delta="",
        prompt_mode="replace",
        negative_prompt_mode="replace",
    )

    assert submitted == 1
    job = controller.job_service.submit_queued.call_args[0][0]
    njr = job._normalized_record
    assert njr.positive_prompt == "new prompt"
    assert njr.negative_prompt == ""
    assert njr.config["steps"] == 20


def test_reprocess_batch_size_groups_only_compatible_jobs(tmp_path) -> None:
    controller = _build_controller()
    image_a = tmp_path / "img_a.png"
    image_b = tmp_path / "img_b.png"
    image_c = tmp_path / "img_c.png"
    image_a.write_bytes(b"")
    image_b.write_bytes(b"")
    image_c.write_bytes(b"")

    def _baseline(path):
        name = path.name
        if name in {"img_a.png", "img_b.png"}:
            return {
                "prompt": "portrait photo",
                "negative_prompt": "blurry",
                "model": "modelA.safetensors",
                "vae": "vaeA",
                "config": {"steps": 28},
            }
        return {
            "prompt": "portrait photo",
            "negative_prompt": "blurry",
            "model": "modelB.safetensors",
            "vae": "vaeA",
            "config": {"steps": 28},
        }

    controller._extract_reprocess_baseline_from_image = Mock(side_effect=_baseline)

    submitted = controller.on_reprocess_images_with_prompt_delta(
        image_paths=[str(image_a), str(image_b), str(image_c)],
        stages=["adetailer"],
        prompt_delta="",
        negative_prompt_delta="",
        prompt_mode="append",
        negative_prompt_mode="append",
        batch_size=2,
    )

    assert submitted == 2
    jobs = [call.args[0] for call in controller.job_service.submit_queued.call_args_list]
    batch_sizes = sorted(len(job._normalized_record.input_image_paths) for job in jobs)
    assert batch_sizes == [1, 2]
