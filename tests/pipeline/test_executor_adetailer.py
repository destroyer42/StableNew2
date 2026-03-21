"""Test ADetailer metadata generation and apply_global handling."""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from src.pipeline.executor import Pipeline


def test_adetailer_metadata_apply_global_defined():
    """Ensure apply_global is defined and False in ADetailer metadata."""
    pipeline = Pipeline(Mock(), Mock())
    
    with patch.object(pipeline, '_load_image_base64', return_value="fake_b64"), \
         patch.object(pipeline, '_generate_images', return_value={"images": ["result_b64"]}), \
         patch('src.pipeline.executor.save_image_from_base64', return_value=True), \
         patch('builtins.open', MagicMock()):
        
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
        }
        
        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
            image_name="test"
        )
        
        assert result is not None
        assert "global_negative_applied" in result
        assert result["global_negative_applied"] is False
        assert result["global_negative_terms"] == ""


def test_adetailer_custom_negative_no_global():
    """ADetailer with custom negative prompt should not apply global terms."""
    pipeline = Pipeline(Mock(), Mock())
    
    with patch.object(pipeline, '_load_image_base64', return_value="fake_b64"), \
         patch.object(pipeline, '_generate_images', return_value={"images": ["result_b64"]}), \
         patch('src.pipeline.executor.save_image_from_base64', return_value=True), \
         patch('builtins.open', MagicMock()):
        
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
            "adetailer_negative_prompt": "custom negative",
        }
        
        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="fallback negative",
            config=config,
            run_dir=Path("output"),
            image_name="test"
        )
        
        assert result is not None
        assert result["global_negative_applied"] is False
        assert result["original_negative_prompt"] == "custom negative"
        assert result["final_negative_prompt"] == "custom negative"


def test_adetailer_inherits_txt2img_negative():
    """ADetailer without custom negative should inherit txt2img negative."""
    pipeline = Pipeline(Mock(), Mock())
    
    with patch.object(pipeline, '_load_image_base64', return_value="fake_b64"), \
         patch.object(pipeline, '_generate_images', return_value={"images": ["result_b64"]}), \
         patch('src.pipeline.executor.save_image_from_base64', return_value=True), \
         patch('builtins.open', MagicMock()):
        
        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
        }
        
        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="inherited negative",
            config=config,
            run_dir=Path("output"),
            image_name="test"
        )
        
        assert result is not None
        assert result["global_negative_applied"] is False
        assert result["original_negative_prompt"] == ""
        assert result["final_negative_prompt"] == "inherited negative"


def test_adetailer_fallback_name_uses_input_stem():
    """Fallback naming should be deterministic when image_name is omitted."""
    pipeline = Pipeline(Mock(), Mock())

    with patch.object(pipeline, '_load_image_base64', return_value="fake_b64"), \
         patch.object(pipeline, '_generate_images', return_value={"images": ["result_b64"]}), \
         patch('src.pipeline.executor.save_image_from_base64', return_value=True), \
         patch('builtins.open', MagicMock()):

        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
        }

        result = pipeline.run_adetailer(
            input_image_path=Path("input portrait.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
        )

        assert result is not None
        assert result["name"] == "adetailer_input_portrait"


def test_adetailer_payload_uses_adaptive_refinement_overrides():
    """Executor should honor runner-provided ADetailer refinement overrides."""
    pipeline = Pipeline(Mock(), Mock())

    with patch.object(pipeline, '_load_image_base64', return_value="fake_b64"), \
         patch.object(pipeline, '_generate_images_with_progress', return_value={"images": ["result_b64"]}) as generate_mock, \
         patch('src.pipeline.executor.save_image_from_base64', return_value=Path("output/test.png")), \
         patch('builtins.open', MagicMock()):

        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 28,
            "adetailer_confidence": 0.22,
            "ad_mask_min_ratio": 0.003,
            "adetailer_padding": 48,
            "ad_use_inpaint_width_height": True,
            "ad_inpaint_width": 768,
            "ad_inpaint_height": 768,
            "adaptive_refinement": {
                "intent": {"mode": "adetailer"},
                "decision_bundle": {
                    "policy_id": "adetailer_micro_face_v1",
                    "applied_overrides": {
                        "ad_confidence": 0.22,
                        "ad_mask_min_ratio": 0.003,
                        "ad_inpaint_only_masked_padding": 48,
                        "ad_use_inpaint_width_height": True,
                        "ad_inpaint_width": 768,
                        "ad_inpaint_height": 768,
                    },
                },
            },
        }

        result = pipeline.run_adetailer(
            input_image_path=Path("input.png"),
            prompt="test prompt",
            negative_prompt="test negative",
            config=config,
            run_dir=Path("output"),
            image_name="test"
        )

        assert result is not None
        payload = generate_mock.call_args.args[1]
        face_args = payload["alwayson_scripts"]["ADetailer"]["args"][2]
        assert face_args["ad_confidence"] == 0.22
        assert face_args["ad_mask_min_ratio"] == 0.003
        assert face_args["ad_inpaint_only_masked_padding"] == 48
        assert face_args["ad_use_inpaint_width_height"] is True
        assert face_args["ad_inpaint_width"] == 768
        assert face_args["ad_inpaint_height"] == 768


def test_adetailer_payload_pins_requested_sd_checkpoint_and_manifest_prefers_it():
    """ADetailer should pin the requested SD model in the payload and manifest."""
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.get_current_model = Mock(return_value="ambient-webui-model.safetensors")

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}) as generate_mock, \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
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
        payload = generate_mock.call_args.args[1]
        assert payload["sd_model"] == "base-model.safetensors"
        assert payload["override_settings"]["sd_model_checkpoint"] == "base-model.safetensors"
        assert result["model"] == "base-model.safetensors"


def test_adetailer_uses_request_override_without_global_model_switch() -> None:
    """ADetailer should pin the request locally without calling WebUI /options model switching."""
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.set_model = Mock()
    pipeline.client.set_vae = Mock()
    pipeline.client.get_current_model = Mock(return_value="ambient-webui-model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="ambient-vae.safetensors")

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}) as generate_mock, \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch("builtins.open", MagicMock()):

        config = {
            "adetailer_enabled": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 20,
            "model": "base-model.safetensors",
            "sd_model_checkpoint": "base-model.safetensors",
            "sd_vae": "base-vae.safetensors",
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
    payload = generate_mock.call_args.args[1]
    assert payload["sd_model"] == "base-model.safetensors"
    assert payload["override_settings"]["sd_model_checkpoint"] == "base-model.safetensors"
    assert payload["sd_vae"] == "base-vae.safetensors"
    assert payload["override_settings"]["sd_vae"] == "base-vae.safetensors"
    pipeline.client.set_model.assert_not_called()
    pipeline.client.set_vae.assert_not_called()
