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
