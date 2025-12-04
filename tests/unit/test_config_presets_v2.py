from pathlib import Path

import pytest

from src.utils.config import ConfigManager


@pytest.fixture
def config_manager(tmp_path: Path) -> ConfigManager:
    return ConfigManager(presets_dir=tmp_path / "presets")


def test_presets_roundtrip_refiner_and_hires_defaults(config_manager: ConfigManager):
    custom_config = {
        "txt2img": {
            "refiner_enabled": True,
            "refiner_model_name": "sdxl_custom_refiner",
            "refiner_switch_at": 0.6,
        },
        "hires_fix": {
            "enabled": True,
            "upscaler_name": "ESRGAN 4x+",
            "upscale_factor": 3.0,
            "steps": 32,
            "denoise": 0.28,
            "use_base_model": False,
        },
    }
    assert config_manager.save_preset("test_refiner", custom_config)
    loaded = config_manager.load_preset("test_refiner")
    assert loaded is not None
    txt2img = loaded["txt2img"]
    assert txt2img["refiner_enabled"] is True
    assert txt2img["refiner_model_name"] == "sdxl_custom_refiner"
    assert abs(txt2img["refiner_switch_at"] - 0.6) < 1e-6
    hires = loaded["hires_fix"]
    assert hires["enabled"] is True
    assert hires["upscaler_name"] == "ESRGAN 4x+"
    assert hires["upscale_factor"] == 3.0
    assert hires["steps"] == 32
    assert abs(hires["denoise"] - 0.28) < 1e-6
    assert hires["use_base_model"] is False


def test_config_defaults_always_include_refiner_hires(config_manager: ConfigManager):
    config = config_manager._merge_config_with_defaults({})
    assert config["txt2img"]["refiner_enabled"] is False
    assert config["txt2img"]["refiner_model_name"] == ""
    assert abs(config["txt2img"]["refiner_switch_at"] - 0.8) < 1e-6
    hires = config["hires_fix"]
    assert hires["upscaler_name"] == "Latent"
    assert hires["hires_upscale_factor"] == 2.0
    assert hires["denoise"] == 0.3
    assert hires["use_base_model"] is True
