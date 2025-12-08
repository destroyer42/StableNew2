from typing import Mapping
from unittest.mock import Mock

from src.controller.pipeline_controller import PipelineController
from src.learning.model_defaults_resolver import ModelDefaultsResolver
from src.utils.config import ConfigManager


def _build_controller() -> PipelineController:
    controller = PipelineController.__new__(PipelineController)
    controller._gui_defaults_resolver = None
    controller._model_defaults_resolver = ModelDefaultsResolver(config_manager=ConfigManager())
    return controller


def test_get_gui_model_defaults_delegates_to_resolver() -> None:
    controller = PipelineController.__new__(PipelineController)
    mock_resolver = Mock()
    default = {"txt2img": {"steps": 25}}
    mock_resolver.resolve_for_gui.return_value = default
    controller._gui_defaults_resolver = mock_resolver
    result = controller.get_gui_model_defaults("juggernaut", "preset-a")
    assert result is default
    mock_resolver.resolve_for_gui.assert_called_once_with(model_name="juggernaut", preset_name="preset-a")


def test_build_merged_config_for_run_applies_style_defaults() -> None:
    controller = _build_controller()
    merged = controller.build_merged_config_for_run("sdxl_portrait_model", preset_name=None)
    hires = merged.get("hires_fix", {})
    assert hires.get("upscaler_name") == "ESRGAN_4x"
    txt2img = merged.get("txt2img", {})
    assert txt2img.get("refiner_model_name") == "sdxl_portrait_refiner"


def test_build_merged_config_for_run_respects_runtime_overrides() -> None:
    controller = _build_controller()
    overrides: Mapping[str, Mapping[str, object]] = {"txt2img": {"refiner_model_name": "custom-refiner"}}
    merged = controller.build_merged_config_for_run("sdxl_portrait_model", runtime_overrides=overrides)
    txt2img = merged.get("txt2img", {})
    assert txt2img.get("refiner_model_name") == "custom-refiner"
