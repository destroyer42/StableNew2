"""Tests for SDXL refiner support in txt2img stage."""

from unittest.mock import Mock

import pytest

from src.pipeline.executor import Pipeline
from src.utils.logger import StructuredLogger


@pytest.fixture
def pipeline_with_mock_client(tmp_path):
    """Create a pipeline with a mock client that captures payloads."""
    mock_client = Mock()
    mock_client.txt2img = Mock(return_value={"images": ["fake_base64_image"]})
    mock_client.set_model = Mock(return_value=True)
    mock_client.set_vae = Mock(return_value=True)
    mock_client.set_hypernetwork = Mock(return_value=True)

    logger = StructuredLogger(output_dir=str(tmp_path))
    pipeline = Pipeline(mock_client, logger)

    return pipeline, mock_client


def test_refiner_adds_override_settings_to_payload(
    tmp_path, pipeline_with_mock_client, monkeypatch
):
    """Test that refiner configuration is passed to API via override_settings."""
    pipeline, mock_client = pipeline_with_mock_client

    # Mock file save to avoid I/O
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", lambda *args: True)

    config = {
        "txt2img": {
            "steps": 25,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "model": "sd_xl_base_1.0.safetensors",
            "refiner_checkpoint": "sd_xl_refiner_1.0.safetensors",
            "refiner_switch_at": 0.8,
        }
    }

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    pipeline.run_txt2img_stage(
        prompt="test prompt",
        negative_prompt="test negative",
        config=config,
        output_dir=output_dir,
        image_name="test_001",
    )

    # Verify txt2img was called
    assert mock_client.txt2img.called
    payload = mock_client.txt2img.call_args[0][0]

    # Verify refiner parameters are at top level of payload
    assert "refiner_checkpoint" in payload
    assert payload["refiner_checkpoint"] == "sd_xl_refiner_1.0.safetensors"
    assert payload["refiner_switch_at"] == 0.8


def test_refiner_not_added_when_disabled(tmp_path, pipeline_with_mock_client, monkeypatch):
    """Test that refiner params are not added when refiner is disabled."""
    pipeline, mock_client = pipeline_with_mock_client

    # Mock file save
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", lambda *args: True)

    config = {
        "txt2img": {
            "steps": 25,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "model": "sd_xl_base_1.0.safetensors",
            "refiner_checkpoint": "None",  # Disabled
            "refiner_switch_at": 0.8,
        }
    }

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    pipeline.run_txt2img_stage(
        prompt="test prompt",
        negative_prompt="test negative",
        config=config,
        output_dir=output_dir,
        image_name="test_001",
    )

    # Verify txt2img was called
    assert mock_client.txt2img.called
    payload = mock_client.txt2img.call_args[0][0]

    # Verify refiner parameters are NOT in payload when disabled
    assert "refiner_checkpoint" not in payload
    assert "refiner_switch_at" not in payload


def test_refiner_not_added_for_invalid_switch_at(tmp_path, pipeline_with_mock_client, monkeypatch):
    """Test that refiner is skipped if switch_at is invalid."""
    pipeline, mock_client = pipeline_with_mock_client

    # Mock file save
    monkeypatch.setattr("src.pipeline.executor.save_image_from_base64", lambda *args: True)

    config = {
        "txt2img": {
            "steps": 25,
            "cfg_scale": 7.0,
            "width": 1024,
            "height": 1024,
            "model": "sd_xl_base_1.0.safetensors",
            "refiner_checkpoint": "sd_xl_refiner_1.0.safetensors",
            "refiner_switch_at": 1.5,  # Invalid: > 1.0
        }
    }

    output_dir = tmp_path / "output"
    output_dir.mkdir()

    pipeline.run_txt2img_stage(
        prompt="test prompt",
        negative_prompt="test negative",
        config=config,
        output_dir=output_dir,
        image_name="test_001",
    )

    # Verify txt2img was called
    assert mock_client.txt2img.called
    payload = mock_client.txt2img.call_args[0][0]

    # Verify refiner parameters are NOT in payload when invalid
    assert "refiner_checkpoint" not in payload
    assert "refiner_switch_at" not in payload
