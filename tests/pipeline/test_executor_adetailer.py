"""Test ADetailer metadata generation and apply_global handling."""
import logging
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
    """ADetailer should preserve the requested SD model in the manifest."""
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.set_model = Mock()
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
        assert "sd_model" not in payload
        assert "override_settings" not in payload
        pipeline.client.set_model.assert_called_once_with("base-model.safetensors")
        assert result["model"] == "base-model.safetensors"


def test_adetailer_defaults_to_global_model_switch_without_request_override() -> None:
    """ADetailer should use the global WebUI switch path by default."""
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
    assert "sd_model" not in payload
    assert "sd_vae" not in payload
    assert "override_settings" not in payload
    pipeline.client.set_model.assert_called_once_with("base-model.safetensors")
    pipeline.client.set_vae.assert_called_once_with("base-vae.safetensors")


def test_adetailer_request_local_pinning_opt_in_uses_request_override(monkeypatch) -> None:
    monkeypatch.setenv("STABLENEW_ADETAILER_REQUEST_LOCAL_PINNING", "1")
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


def test_adetailer_diagnostics_log_request_payload_fields(monkeypatch, caplog) -> None:
    monkeypatch.setenv("STABLENEW_ADETAILER_REQUEST_LOCAL_PINNING", "1")
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.get_current_model = Mock(return_value="ambient-webui-model.safetensors")
    pipeline.client.get_current_vae = Mock(return_value="ambient-vae.safetensors")

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch("builtins.open", MagicMock()), \
         caplog.at_level(logging.INFO):

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
    diagnostic_messages = [
        record.message for record in caplog.records if "[adetailer/diagnostics]" in record.message
    ]
    assert diagnostic_messages
    assert any("payload_sd_vae=base-vae.safetensors" in message for message in diagnostic_messages)
    assert any("payload_override_vae=base-vae.safetensors" in message for message in diagnostic_messages)
    assert any("payload_sd_model=base-model.safetensors" in message for message in diagnostic_messages)
    assert all("actual_webui_vae" not in message for message in diagnostic_messages)


def test_adetailer_logs_exact_request_args_block(caplog) -> None:
    pipeline = Pipeline(Mock(), Mock())

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch("builtins.open", MagicMock()), \
         caplog.at_level(logging.INFO):

        config = {
            "adetailer_enabled": True,
            "enable_face_pass": True,
            "enable_hands_pass": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 7,
            "adetailer_cfg": 4.0,
            "adetailer_denoise": 0.13,
            "adetailer_sampler": "DPM++ 2M",
            "adetailer_hands_model": "hand_yolov8n.pt",
            "adetailer_hands_steps": 6,
            "adetailer_hands_cfg": 4.5,
            "adetailer_hands_denoise": 0.2,
            "adetailer_hands_sampler": "Euler a",
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
    args_messages = [
        record.message for record in caplog.records if record.message.startswith("[adetailer/args] ")
    ]
    assert len(args_messages) == 1
    args_message = args_messages[0]
    assert '"ad_model": "face_yolov8n.pt"' in args_message
    assert '"ad_model": "hand_yolov8n.pt"' in args_message
    assert '"ad_steps": 7' in args_message
    assert '"ad_steps": 6' in args_message
    assert '"ad_sampler": "DPM++ 2M"' in args_message
    assert '"ad_sampler": "Euler a"' in args_message


def test_adetailer_normalizes_scheduler_and_respects_explicit_pass_enables() -> None:
    pipeline = Pipeline(Mock(), Mock())

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}) as generate_mock, \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch("builtins.open", MagicMock()):

        config = {
            "adetailer_enabled": True,
            "enable_face_pass": False,
            "enable_hands_pass": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_steps": 20,
            "adetailer_scheduler": "inherit",
            "adetailer_hands_scheduler": "Use same scheduler",
            "ad_hands_use_inpaint_width_height": True,
            "ad_hands_inpaint_width": 640,
            "ad_hands_inpaint_height": 896,
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
    face_args = payload["alwayson_scripts"]["ADetailer"]["args"][2]
    hand_args = payload["alwayson_scripts"]["ADetailer"]["args"][3]
    assert face_args["ad_tab_enable"] is False
    assert face_args["ad_scheduler"] == "Use same scheduler"
    assert hand_args["ad_tab_enable"] is True
    assert hand_args["ad_scheduler"] == "Use same scheduler"
    assert hand_args["ad_use_inpaint_width_height"] is True
    assert hand_args["ad_inpaint_width"] == 640
    assert hand_args["ad_inpaint_height"] == 896


def test_adetailer_experiment_legacy_safe_payload_sanitizes_pass_args(monkeypatch) -> None:
    monkeypatch.setenv("STABLENEW_ADETAILER_EXPERIMENT_LEGACY_SAFE_PAYLOAD", "1")
    pipeline = Pipeline(Mock(), Mock())

    with patch.object(pipeline, "_load_image_base64", return_value="fake_b64"), \
         patch.object(pipeline, "_generate_images_with_progress", return_value={"images": ["result_b64"]}) as generate_mock, \
         patch("src.pipeline.executor.Image.open", side_effect=FileNotFoundError), \
         patch("src.pipeline.executor.save_image_from_base64", return_value=Path("output/test.png")), \
         patch("builtins.open", MagicMock()):

        config = {
            "adetailer_enabled": True,
            "enable_face_pass": True,
            "enable_hands_pass": True,
            "adetailer_model": "face_yolov8n.pt",
            "adetailer_scheduler": "Karras",
            "ad_inpaint_only_masked": False,
            "ad_use_inpaint_width_height": True,
            "ad_inpaint_width": 640,
            "ad_inpaint_height": 896,
            "adetailer_hands_model": "hand_yolov8n.pt",
            "adetailer_hands_scheduler": "Karras",
            "ad_hands_inpaint_only_masked": False,
            "ad_hands_use_inpaint_width_height": True,
            "ad_hands_inpaint_width": 640,
            "ad_hands_inpaint_height": 896,
            "width": 768,
            "height": 1024,
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
    face_args = payload["alwayson_scripts"]["ADetailer"]["args"][2]
    hand_args = payload["alwayson_scripts"]["ADetailer"]["args"][3]
    assert face_args["ad_inpaint_only_masked"] is True
    assert face_args["ad_use_inpaint_width_height"] is False
    assert face_args["ad_inpaint_width"] == 768
    assert face_args["ad_inpaint_height"] == 1024
    assert face_args["ad_scheduler"] == "Use same scheduler"
    assert hand_args["ad_inpaint_only_masked"] is True
    assert hand_args["ad_use_inpaint_width_height"] is False
    assert hand_args["ad_inpaint_width"] == 768
    assert hand_args["ad_inpaint_height"] == 1024
    assert hand_args["ad_scheduler"] == "Use same scheduler"


def test_check_model_drift_downgrades_request_local_ambient_mismatch(caplog) -> None:
    pipeline = Pipeline(Mock(), Mock())
    pipeline.client.get_current_model = Mock(return_value="juggernautXL_ragnarokBy.safetensors [dd08fa32f9]")

    with caplog.at_level(logging.INFO):
        warning = pipeline._check_model_drift(
            stage_name="txt2img",
            requested_model="epicrealismXL_vxviiCrystalclear.safetensors",
            when="entry",
            request_local_override_expected=True,
        )

    assert warning is None
    assert any(
        "ambient /options model differs while request-local override is active" in record.message
        for record in caplog.records
    )
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)
