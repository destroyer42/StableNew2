from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from src.pipeline.executor import Pipeline

_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0ioAAAAASUVORK5CYII="
)


def test_adetailer_manifest_carries_canonical_adaptive_refinement_block() -> None:
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.get_current_model = Mock(return_value="model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="vae.pt")

    adaptive_refinement = {
        "intent": {
            "schema": "stablenew.adaptive-refinement.v1",
            "enabled": True,
            "mode": "adetailer",
            "profile_id": "auto_v1",
            "detector_preference": "null",
            "record_decisions": True,
            "algorithm_version": "v1",
        },
        "prompt_intent": {
            "intent_band": "portrait",
            "requested_pose": "profile",
            "wants_face_detail": True,
        },
        "decision_bundle": {
            "schema": "stablenew.refinement-decision.v1",
            "algorithm_version": "v1",
            "mode": "adetailer",
            "policy_id": "adetailer_micro_face_v1",
            "detector_id": "null",
            "observation": {
                "subject_assessment": {
                    "detector_id": "null",
                    "scale_band": "micro",
                }
            },
            "applied_overrides": {
                "ad_confidence": 0.22,
                "ad_mask_min_ratio": 0.003,
                "ad_inpaint_only_masked_padding": 48,
            },
            "prompt_patch": {
                "add_positive": ["clear irises"],
                "remove_positive": ["soft face"],
            },
            "notes": ["small_subject_recovery"],
        },
        "detector_notes": [],
    }

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch.object(pipeline, "_write_manifest_file") as write_manifest_mock, \
         patch("builtins.open", MagicMock()):
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
            "adetailer_confidence": 0.22,
            "ad_mask_min_ratio": 0.003,
            "adetailer_padding": 48,
            "adaptive_refinement": adaptive_refinement,
        }

        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
            image_name="test",
        )

    assert result is not None
    assert result["adaptive_refinement"]["decision_bundle"]["policy_id"] == "adetailer_micro_face_v1"
    assert result["adaptive_refinement"]["decision_bundle"]["applied_overrides"] == {
        "ad_confidence": 0.22,
        "ad_mask_min_ratio": 0.003,
        "ad_inpaint_only_masked_padding": 48,
    }
    manifest_metadata = write_manifest_mock.call_args.kwargs["metadata"]
    assert manifest_metadata["adaptive_refinement"]["intent"]["mode"] == "adetailer"
    assert manifest_metadata["adaptive_refinement"]["decision_bundle"]["policy_id"] == "adetailer_micro_face_v1"
    assert manifest_metadata["adaptive_refinement"]["prompt_patch_provenance"]["stage_name"] == "adetailer"
    assert (
        manifest_metadata["adaptive_refinement"]["prompt_patch_provenance"]["positive"]["applied_add"]
        == ["clear irises"]
    )


def test_adetailer_manifest_model_prefers_requested_stage_checkpoint() -> None:
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.get_current_model = Mock(return_value="ambient-webui-model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="vae.pt")

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch.object(pipeline, "_write_manifest_file") as write_manifest_mock, \
         patch("builtins.open", MagicMock()):
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 20,
            "model": "base-model.safetensors",
            "sd_model_checkpoint": "base-model.safetensors",
        }

        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
            image_name="test",
        )

    assert result is not None
    manifest_metadata = write_manifest_mock.call_args.kwargs["metadata"]
    assert manifest_metadata["model"] == "base-model.safetensors"


def test_upscale_single_mode_uses_extended_timeout_without_global_model_switch() -> None:
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.set_model = Mock()
    pipeline.client.set_vae = Mock()
    pipeline.client.get_current_model = Mock(return_value="ambient-webui-model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="ambient-vae.safetensors")

    captured: dict[str, object] = {}

    def _upscale_image(**kwargs):
        captured.update(kwargs)
        return {"image": "result_b64"}

    pipeline.client.upscale_image = Mock(side_effect=_upscale_image)

    with patch.object(pipeline, "_load_image_base64", return_value=_TINY_PNG_BASE64), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch.object(pipeline, "_write_manifest_file") as write_manifest_mock:
        config = {
            "upscale_mode": "single",
            "upscaler": "R-ESRGAN 4x+",
            "upscaling_resize": 2.0,
            "model": "base-model.safetensors",
            "sd_model_checkpoint": "base-model.safetensors",
            "sd_vae": "base-vae.safetensors",
        }

        result = pipeline.run_upscale_stage(
            input_image_path=Path("input.png"),
            config=config,
            output_dir=Path("output"),
            image_name="test_upscale",
        )

    assert result is not None
    assert captured["timeout"] == 300.0
    pipeline.client.set_model.assert_not_called()
    pipeline.client.set_vae.assert_not_called()
    manifest_metadata = write_manifest_mock.call_args.kwargs["metadata"]
    assert manifest_metadata["model"] == "base-model.safetensors"
    assert manifest_metadata["vae"] == "base-vae.safetensors"


def test_upscale_img2img_pins_requested_stage_checkpoint_without_global_switch() -> None:
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.set_model = Mock()
    pipeline.client.set_vae = Mock()
    pipeline.client.get_current_model = Mock(return_value="ambient-webui-model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="ambient-vae.safetensors")

    with patch.object(pipeline, "_load_image_base64", return_value=_TINY_PNG_BASE64), \
         patch.object(pipeline, "_generate_images", return_value={"images": ["result_b64"]}) as generate_mock, \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch.object(pipeline, "_write_manifest_file") as write_manifest_mock:
        config = {
            "upscale_mode": "img2img",
            "upscaler": "R-ESRGAN 4x+",
            "upscaling_resize": 2.0,
            "steps": 18,
            "denoising_strength": 0.2,
            "model": "base-model.safetensors",
            "sd_model_checkpoint": "base-model.safetensors",
            "sd_vae": "base-vae.safetensors",
        }

        result = pipeline.run_upscale_stage(
            input_image_path=Path("input.png"),
            config=config,
            output_dir=Path("output"),
            image_name="test_upscale_img2img",
        )

    assert result is not None
    payload = generate_mock.call_args.args[1]
    assert payload["sd_model"] == "base-model.safetensors"
    assert payload["sd_vae"] == "base-vae.safetensors"
    assert payload["override_settings"]["sd_model_checkpoint"] == "base-model.safetensors"
    assert payload["override_settings"]["sd_vae"] == "base-vae.safetensors"
    pipeline.client.set_model.assert_not_called()
    pipeline.client.set_vae.assert_not_called()
    manifest_metadata = write_manifest_mock.call_args.kwargs["metadata"]
    assert manifest_metadata["model"] == "base-model.safetensors"
    assert manifest_metadata["vae"] == "base-vae.safetensors"
